import time

from helpers.extension import Extension
from agent import AgentContext, LoopData
from helpers.defer import DeferredTask, THREAD_BACKGROUND
from helpers import model_concurrency, perf, persist_chat

DATA_NAME_TASK = "_organize_history_task"

# An early pass waits for a real gap. Started right after a step it was
# interrupted by the next step's model call almost every time (233 of 1,983
# compression calls ended in under a second, each one swapping the server's
# slot for nothing). Longer than an ordinary gap between steps.
SOFT_IDLE_SETTLE_SECONDS = 15.0
SOFT_MAX_WAIT_SECONDS = 1800.0


async def _wait_for_a_gap(history) -> bool:
    """True once the model has been free for a while, or history is over its
    limit (then a turn is waiting for this pass). False if neither came."""
    started = time.monotonic()
    while not history.is_over_limit():
        if await model_concurrency.wait_for_foreground_idle(SOFT_IDLE_SETTLE_SECONDS, 1.0):
            return True
        if time.monotonic() - started >= SOFT_MAX_WAIT_SECONDS:
            return False
    return True


def _chat_is_gone(history) -> bool:
    context = getattr(history.agent, "context", None)
    return context is not None and AgentContext.get(context.id) is not context


async def _save_if_idle(history) -> None:
    """Keep the pass's work: the step's own save ran before this pass finished,
    and a pass at the end of a turn has no later step to save it. Without this,
    closing the window lost the summaries and the next start redid them all
    (seen: the same 11 calls twice, about 45 s each time). During a turn the
    next step saves; a chat deleted meanwhile must not be written back.
    """
    context = getattr(history.agent, "context", None)
    if context is None or _chat_is_gone(history) or context.is_running():
        return
    try:
        await persist_chat.save_tmp_chat_async(context)
    except Exception:
        pass  # the next regular save covers it


async def soft_compress(history):
    """Early compression at low priority (see history.SOFT_TRIGGER_RATIO).

    Its model calls are background work: they wait for a gap, queue behind the
    user's turn and are interrupted when a turn needs the model. Returns None
    when it did not get to finish, so the waiting side knows nothing was
    achieved and retries itself; a False/True result is the usual "compressed
    anything?".
    """
    if not history.wants_soft_compress():
        return False
    if not await _wait_for_a_gap(history) or _chat_is_gone(history):
        return None
    before = history.get_tokens()
    try:
        result = await perf.tagged("history_compression", background=True)(history.compress)(soft=True)
    except model_concurrency.Preempted:
        result = None
    if history.get_tokens() != before:  # an interrupted pass can have done part of the work
        await _save_if_idle(history)
    return result


class OrganizeHistory(Extension):
    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent:
            return

        # is there a running task? if yes, skip this round, the wait extension will double check the context size
        task: DeferredTask|None = self.agent.get_data(DATA_NAME_TASK)
        if task and not task.is_ready():
            return

        # start task
        task = DeferredTask(thread_name=THREAD_BACKGROUND)
        task.start_task(soft_compress, self.agent.history)
        # set to agent to be able to wait for it
        self.agent.set_data(DATA_NAME_TASK, task)

from helpers.extension import Extension
from agent import LoopData
from helpers.defer import DeferredTask, THREAD_BACKGROUND
from helpers import model_concurrency, perf

DATA_NAME_TASK = "_organize_history_task"


async def soft_compress(history):
    """Early compression at low priority (see history.SOFT_TRIGGER_RATIO).

    Its model calls are background work: they queue behind the user's turn and
    are interrupted when a turn needs the model. Returns None when that
    happened, so the waiting side knows nothing was achieved and retries
    itself; a False/True result is the usual "compressed anything?".
    """
    try:
        return await perf.tagged("history_compression", background=True)(history.compress)(soft=True)
    except model_concurrency.Preempted:
        return None


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

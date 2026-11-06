"""Early ("soft") history compression: it runs before a turn has to wait for it.

Hard compression starts only when history is over its budget, so a long chat
stalls its next step on summarizing every time it reaches the limit. The soft
pass starts at 85% of the budget, runs in the background at low priority, only
summarizes (never drops a record) and steps aside for the user's turn.
"""

import asyncio

import pytest

from helpers import history as history_mod
from helpers import model_concurrency
from helpers.history import History

BUDGET = 10000


class _Agent:
    """Just enough agent for History: a budget, prompts, a summarizer."""

    def __init__(self):
        self.summaries = 0
        self.fail_with = None

    def read_prompt(self, name, **kwargs):
        return "sys" if name.endswith("sys.md") else str(kwargs.get("content", ""))

    def parse_prompt(self, name, **kwargs):
        return "SUMMARY " + str(kwargs.get("summary", ""))

    async def call_utility_model(self, system="", message="", **kwargs):
        if self.fail_with is not None:
            raise self.fail_with
        self.summaries += 1
        return "short summary"


@pytest.fixture
def make_history(monkeypatch):
    monkeypatch.setattr(history_mod, "get_chat_model_config", lambda agent=None: {"ctx_length": 100000, "ctx_history": 0.1})
    monkeypatch.setattr(history_mod, "get_utility_model_config", lambda agent=None: {"ctx_length": 100000})
    monkeypatch.setattr(History, "_get_ctx_size_for_history", lambda self: BUDGET)
    from extensions.python.message_loop_end import _10_organize_history as ext

    monkeypatch.setattr(ext, "SOFT_IDLE_SETTLE_SECONDS", 0.0)  # no waiting for a gap unless a test wants it

    def build(target_tokens):
        """One topic of equal messages, up to just past `target_tokens`."""
        history = History(agent=_Agent())
        i = 0
        while history.get_tokens() < target_tokens:
            history.add_message(ai=bool(i % 2), content=f"message {i} " + "word " * 150)
            i += 1
        return history

    return build


def test_below_the_soft_trigger_nothing_happens(make_history):
    history = make_history(int(BUDGET * 0.7))
    assert history.get_tokens() < BUDGET * history_mod.SOFT_TRIGGER_RATIO
    assert asyncio.run(history.compress(soft=True)) is False
    assert history.agent.summaries == 0


def test_between_the_trigger_and_the_limit_the_soft_pass_compresses(make_history):
    history = make_history(int(BUDGET * 0.95))
    before = history.get_tokens()
    assert BUDGET * history_mod.SOFT_TRIGGER_RATIO < before <= BUDGET
    assert not history.is_over_limit()  # a hard pass would do nothing yet
    assert asyncio.run(history.compress()) is False
    assert asyncio.run(history.compress(soft=True)) is True
    assert history.get_tokens() < before
    assert history.get_tokens() <= BUDGET * history_mod.SOFT_TARGET_RATIO
    assert history.agent.summaries >= 1


def test_the_soft_pass_never_drops_a_bulk(make_history):
    history = make_history(int(BUDGET * 0.9))
    for _ in range(5):
        bulk = history_mod.Bulk(history=history)
        bulk.summary = "old " + "word " * 100
        history.bulks.append(bulk)
    assert history.get_tokens() > BUDGET * history_mod.SOFT_TRIGGER_RATIO
    asyncio.run(history.compress(soft=True))
    assert history.bulks  # summarized or merged, never popped away


def test_compress_bulks_only_drops_when_allowed(make_history):
    history = make_history(100)
    bulk = history_mod.Bulk(history=history)
    bulk.summary = "x"
    history.bulks.append(bulk)

    async def no_merge(count):
        return False

    history.merge_bulks_by = no_merge
    assert asyncio.run(history.compress_bulks(allow_drop=False)) is False
    assert len(history.bulks) == 1
    assert asyncio.run(history.compress_bulks()) is True
    assert history.bulks == []


def test_a_turn_that_needs_the_model_interrupts_the_soft_pass_without_an_error(make_history):
    from extensions.python.message_loop_end import _10_organize_history as ext

    history = make_history(int(BUDGET * 0.95))
    history.agent.fail_with = model_concurrency.Preempted("a turn needs the model")
    assert asyncio.run(ext.soft_compress(history)) is None  # stepped aside, no exception


def test_the_soft_pass_models_calls_are_background_work_and_preemptible(make_history):
    import models
    from extensions.python.message_loop_end import _10_organize_history as ext
    from helpers import perf

    seen = {}

    async def spy(self, system="", message="", **kwargs):
        seen["caller"], seen["background"] = perf.CALLER.get(), perf.BACKGROUND.get()
        return "short summary"

    history = make_history(int(BUDGET * 0.95))
    history.agent.call_utility_model = spy.__get__(history.agent)
    assert asyncio.run(ext.soft_compress(history)) is True
    assert seen == {"caller": "history_compression", "background": True}
    assert "history_compression" in models.PREEMPTIBLE_CALLERS


def test_the_blocking_path_is_not_background_work(make_history):
    from helpers import perf

    seen = {}

    async def spy(self, system="", message="", **kwargs):
        seen["background"] = perf.BACKGROUND.get()
        return "short summary"

    history = make_history(int(BUDGET * 1.5))
    history.agent.call_utility_model = spy.__get__(history.agent)
    asyncio.run(history.compress())
    assert seen["background"] is False  # the turn is waiting for this one


def test_the_wait_hook_compresses_itself_when_the_soft_pass_stepped_aside():
    from extensions.python.message_loop_end._10_organize_history import DATA_NAME_TASK
    from extensions.python.message_loop_prompts_before._90_organize_history_wait import OrganizeHistoryWait

    class _Task:
        def is_ready(self):
            return True

        async def result(self):
            return None  # preempted

    class _History:
        def __init__(self):
            self.tokens, self.compress_calls = 2000, 0

        def is_over_limit(self):
            return self.tokens > 1000

        def get_tokens(self):
            return self.tokens

        async def compress(self):
            self.compress_calls += 1
            self.tokens = 900
            return True

    class _Log:
        entries = []

        def set_progress(self, *a, **k):
            pass

        def log(self, **kwargs):
            self.entries.append(kwargs)

    class _Agent:
        def __init__(self):
            self.data = {DATA_NAME_TASK: _Task()}
            self.history = _History()
            self.context = type("C", (), {"log": _Log()})()

        def get_data(self, key):
            return self.data.get(key)

        def set_data(self, key, value):
            self.data[key] = value

    agent = _Agent()
    asyncio.run(OrganizeHistoryWait(agent).execute())
    assert agent.history.compress_calls == 1  # compressed in the turn
    assert agent.context.log.entries == []  # and no false "stalled" warning


# -- when the early pass runs, and keeping its work --------------------------------------

def _ext():
    from extensions.python.message_loop_end import _10_organize_history as ext

    return ext


def test_nothing_to_do_returns_at_once_without_waiting(make_history, monkeypatch):
    history = make_history(int(BUDGET * 0.7))

    async def must_not_wait(*a, **k):
        raise AssertionError("waited for a gap with nothing to do")

    monkeypatch.setattr(model_concurrency, "wait_for_foreground_idle", must_not_wait)
    assert asyncio.run(_ext().soft_compress(history)) is False


def test_the_early_pass_waits_for_a_gap_between_steps(make_history, monkeypatch):
    history = make_history(int(BUDGET * 0.95))
    idle_after = [False, False, True]

    async def idle(settle, max_wait):
        assert history.agent.summaries == 0  # nothing summarized while the turn is busy
        return idle_after.pop(0)

    monkeypatch.setattr(model_concurrency, "wait_for_foreground_idle", idle)
    assert asyncio.run(_ext().soft_compress(history)) is True
    assert idle_after == [] and history.agent.summaries >= 1


def test_it_goes_at_once_when_a_turn_is_waiting_for_it(make_history, monkeypatch):
    history = make_history(int(BUDGET * 1.2))  # over the limit: the turn blocks on this pass
    assert history.is_over_limit()

    async def never_idle(settle, max_wait):
        raise AssertionError("must not wait for a gap when over the limit")

    monkeypatch.setattr(model_concurrency, "wait_for_foreground_idle", never_idle)
    assert asyncio.run(_ext().soft_compress(history)) is True


def test_it_gives_up_when_no_gap_ever_comes(make_history, monkeypatch):
    ext = _ext()
    history = make_history(int(BUDGET * 0.95))

    async def busy(settle, max_wait):
        return False

    monkeypatch.setattr(model_concurrency, "wait_for_foreground_idle", busy)
    monkeypatch.setattr(ext, "SOFT_MAX_WAIT_SECONDS", 0.0)
    assert asyncio.run(ext.soft_compress(history)) is None
    assert history.agent.summaries == 0


class _Ctx:
    id = "chat-1"

    def __init__(self, running=False):
        self.running = running

    def is_running(self):
        return self.running


def _with_context(history, monkeypatch, *, registered=True, running=False):
    ext = _ext()
    context = _Ctx(running)
    history.agent.context = context
    monkeypatch.setattr(ext.AgentContext, "get", staticmethod(lambda id: context if registered else None))
    saved = []

    async def save(ctx):
        saved.append(ctx)

    monkeypatch.setattr(ext.persist_chat, "save_tmp_chat_async", save)
    return ext, saved


def test_the_passes_work_is_saved_so_a_restart_does_not_redo_it(make_history, monkeypatch):
    history = make_history(int(BUDGET * 0.95))
    ext, saved = _with_context(history, monkeypatch)
    assert asyncio.run(ext.soft_compress(history)) is True
    assert saved == [history.agent.context]


def test_nothing_is_saved_when_nothing_changed(make_history, monkeypatch):
    history = make_history(int(BUDGET * 0.7))
    ext, saved = _with_context(history, monkeypatch)
    assert asyncio.run(ext.soft_compress(history)) is False
    assert saved == []


def test_a_running_turn_saves_for_itself(make_history, monkeypatch):
    history = make_history(int(BUDGET * 0.95))
    ext, saved = _with_context(history, monkeypatch, running=True)
    asyncio.run(ext.soft_compress(history))
    assert saved == []


def test_a_deleted_chat_is_not_summarized_or_written_back(make_history, monkeypatch):
    history = make_history(int(BUDGET * 0.95))
    ext, saved = _with_context(history, monkeypatch, registered=False)
    assert asyncio.run(ext.soft_compress(history)) is None
    assert saved == [] and history.agent.summaries == 0


def test_work_done_before_an_interruption_is_kept_too(make_history, monkeypatch):
    history = make_history(int(BUDGET * 0.95))
    ext, saved = _with_context(history, monkeypatch)

    async def partial(soft=False):
        history.current.messages[1:3] = []  # one summary landed, then the turn took the model
        raise model_concurrency.Preempted("a turn needs the model")

    monkeypatch.setattr(history, "compress", partial)
    assert asyncio.run(ext.soft_compress(history)) is None
    assert saved == [history.agent.context]

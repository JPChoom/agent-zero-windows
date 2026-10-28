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

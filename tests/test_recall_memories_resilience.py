"""A broken memory-recall prompt must not crash the turn.

call_extensions_async has no generic per-extension error handling (see
helpers/extension.py) - an exception raised by any single extension
propagates and aborts every extension still due to run at that point,
which for message_loop_prompts_after means the rest of prompt assembly
for that turn. Memory recall is a best-effort enrichment: a missing or
broken prompt template should cost this feature for the turn, not the
turn itself.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from plugins._memory.extensions.python.message_loop_prompts_after import (
    _50_recall_memories as recall_mod,
)

FAKE_CONFIG = {
    "memory_recall_enabled": True,
    "memory_recall_interval": 1,
    "memory_recall_history_len": 10000,
    "memory_recall_query_prep": True,
    "memory_recall_memories_max_search": 5,
    "memory_recall_solutions_max_search": 3,
    "memory_recall_memories_max_result": 5,
    "memory_recall_solutions_max_result": 3,
    "memory_recall_similarity_threshold": 0.6,
    "memory_recall_post_filter": False,
}


@pytest.fixture(autouse=True)
def _fake_plugin_config(monkeypatch):
    monkeypatch.setattr(
        recall_mod.plugins, "get_plugin_config", lambda name, agent=None: dict(FAKE_CONFIG)
    )


class _LogItem:
    def __init__(self):
        self.updates = []

    def update(self, **kw):
        self.updates.append(kw)


class _Log:
    def __init__(self):
        self.logs = []

    def log(self, **kw):
        self.logs.append(kw)
        return _LogItem()


class _Context:
    def __init__(self):
        self.log = _Log()


class _History:
    def __init__(self, text="some prior conversation"):
        self._text = text

    def output_text(self):
        return self._text


class _Agent:
    def __init__(self):
        self.context = _Context()
        self.history = _History()

    def read_prompt(self, *a, **k):
        raise FileNotFoundError("memory.memories_query.sys.md missing")

    async def call_utility_model(self, *a, **k):
        raise AssertionError("must not be reached - prompt read already failed")


class _LoopData:
    def __init__(self, user_message=None):
        self.user_message = user_message
        self.extras_persistent = {}


@pytest.mark.asyncio
async def test_a_broken_prompt_template_does_not_raise():
    """The regression this guards against: read_prompt raising here used
    to propagate straight out of search_memories, and from there out of
    the extension point call, aborting whatever else message_loop_prompts_after
    still had to run for the turn."""
    agent = _Agent()
    ext = recall_mod.RecallMemories(agent=agent)  # type: ignore[arg-type]
    log_item = _LogItem()

    # Must not raise.
    await ext.search_memories(log_item=log_item, loop_data=_LoopData())


@pytest.mark.asyncio
async def test_the_failure_is_logged_not_silent():
    agent = _Agent()
    ext = recall_mod.RecallMemories(agent=agent)  # type: ignore[arg-type]
    log_item = _LogItem()

    await ext.search_memories(log_item=log_item, loop_data=_LoopData())

    assert agent.context.log.logs, "the failure must be visible somewhere"
    entry = agent.context.log.logs[0]
    assert entry["type"] == "warning"
    assert "missing" in entry["content"].lower() or "memories_query" in entry["content"]
    assert log_item.updates and "Failed" in log_item.updates[-1].get("heading", "")


@pytest.mark.asyncio
async def test_a_working_prompt_is_unaffected():
    """The guard must only catch, not change behaviour on the happy path."""

    class _WorkingAgent(_Agent):
        def read_prompt(self, name, **k):
            if name == "memory.memories_query.sys.md":
                return "SYS"
            return "MSG:" + str(k.get("history", ""))

        async def call_utility_model(self, *a, **k):
            return "-"  # a query this short short-circuits before any DB call

    agent = _WorkingAgent()
    ext = recall_mod.RecallMemories(agent=agent)  # type: ignore[arg-type]
    log_item = _LogItem()

    class _Msg:
        def output_text(self):
            return "hello"

    await ext.search_memories(log_item=log_item, loop_data=_LoopData(user_message=_Msg()))
    # Reached the "no relevant query" short-circuit rather than the
    # exception path - proves the try/except doesn't swallow success.
    assert not any(e["type"] == "warning" for e in agent.context.log.logs)

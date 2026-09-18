import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from extensions.python.message_loop_prompts_before._90_organize_history_wait import (
    MAX_SYNC_COMPRESSION_PASSES,
    OrganizeHistoryWait,
)
from extensions.python.message_loop_end._10_organize_history import DATA_NAME_TASK


class _StalledHistory:
    def __init__(self):
        self.compress_calls = 0

    def is_over_limit(self):
        return self.compress_calls < 2

    def get_tokens(self):
        return 1234

    async def compress(self):
        self.compress_calls += 1
        return False


class _MaxPassHistory:
    def __init__(self):
        self.compress_calls = 0
        self.tokens = 2000

    def is_over_limit(self):
        return True

    def get_tokens(self):
        return self.tokens

    async def compress(self):
        self.compress_calls += 1
        self.tokens -= 1
        return True


class _FakeLog:
    def __init__(self):
        self.entries = []

    def set_progress(self, *args, **kwargs):
        pass

    def log(self, **kwargs):
        self.entries.append(kwargs)


class _FakeAgent:
    def __init__(self, history=None):
        self.data = {}
        self.history = history or _StalledHistory()
        self.context = type("Context", (), {"log": _FakeLog()})()

    def get_data(self, key):
        return self.data.get(key)

    def set_data(self, key, value):
        self.data[key] = value


@pytest.mark.asyncio
async def test_history_wait_stops_when_compression_makes_no_progress():
    agent = _FakeAgent()

    await OrganizeHistoryWait(agent).execute()

    assert agent.history.compress_calls == 1
    assert agent.context.log.entries
    assert agent.context.log.entries[-1]["heading"] == "History compression stalled"


@pytest.mark.asyncio
async def test_history_wait_stops_after_max_sync_compression_passes():
    history = _MaxPassHistory()
    agent = _FakeAgent(history)

    await OrganizeHistoryWait(agent).execute()

    assert history.compress_calls == MAX_SYNC_COMPRESSION_PASSES
    assert agent.context.log.entries
    assert agent.context.log.entries[-1]["heading"] == "History compression stalled"
    assert (
        f"stopped after {MAX_SYNC_COMPRESSION_PASSES} passes"
        in agent.context.log.entries[-1]["content"]
    )


class _AlreadyDoneTask:
    """A background compression task that finished before the wait loop ran.

    This is the normal case: message_loop_end starts compression, and by
    the time the next turn reaches message_loop_prompts_before it is often
    already complete.
    """

    def __init__(self):
        self.awaited = False

    def is_ready(self):
        return True

    async def result(self):
        self.awaited = True
        return True


class _PreCompressedHistory:
    """History the background task already reduced - but not far enough."""

    def __init__(self):
        self.tokens = 37789
        self.compress_calls = 0

    def is_over_limit(self):
        return self.tokens > 34834

    def get_tokens(self):
        return self.tokens

    async def compress(self):
        self.compress_calls += 1
        self.tokens -= 5000
        return True


@pytest.mark.asyncio
async def test_a_finished_task_is_not_scored_as_this_passes_progress():
    """Regression: the task's reduction is already inside before_tokens, so
    comparing before/after compares history against itself. That read as
    "no progress" and abandoned compression on the very first pass, leaving
    history over budget - which produced a 53,090-token prompt in a 65,536
    window and a hard "Context size has been exceeded" from the provider.
    """
    history = _PreCompressedHistory()
    agent = _FakeAgent(history=history)
    task = _AlreadyDoneTask()
    agent.data[DATA_NAME_TASK] = task

    await OrganizeHistoryWait(agent).execute()

    assert task.awaited, "the finished task must still be consumed"
    assert history.compress_calls > 0, (
        "compression must continue synchronously after consuming a task "
        "that finished before the loop started"
    )
    assert not history.is_over_limit(), "history must end within budget"
    assert agent.data[DATA_NAME_TASK] is None, "the task must be cleared"


@pytest.mark.asyncio
async def test_a_finished_task_cannot_loop_forever():
    """Consuming a finished task and re-evaluating must still respect the
    pass ceiling, or a history that cannot shrink would spin."""
    class _Immovable(_PreCompressedHistory):
        async def compress(self):
            self.compress_calls += 1
            return True  # claims success, reduces nothing

    agent = _FakeAgent(history=_Immovable())
    agent.data[DATA_NAME_TASK] = _AlreadyDoneTask()

    await OrganizeHistoryWait(agent).execute()
    assert agent.history.compress_calls <= MAX_SYNC_COMPRESSION_PASSES


class _StalledProviderHistory:
    """A synchronous compress() call whose provider stalls - the real
    incident: agent.call_utility_model used to await the provider with no
    timeout, leaving this wait stuck on "Compressing history..." forever."""

    def is_over_limit(self):
        return True

    def get_tokens(self):
        return 5000

    async def compress(self):
        raise TimeoutError("Utility model call timed out after 180s")


@pytest.mark.asyncio
async def test_a_stalled_provider_call_does_not_hang_the_turn():
    """Regression: an unbounded provider wait inside compress() used to
    block this extension - and the whole turn - indefinitely. A raised
    TimeoutError must be caught and treated as a stalled pass, not left to
    propagate out of message_loop_prompts_before."""
    agent = _FakeAgent(history=_StalledProviderHistory())

    # Must not raise, and must not hang.
    await OrganizeHistoryWait(agent).execute()

    assert agent.context.log.entries
    entry = agent.context.log.entries[-1]
    assert entry["heading"] == "History compression stalled"
    assert "timed out" in entry["content"]


class _StalledTask:
    """A background compression task whose provider call stalled - the
    exception surfaces through result(), mirroring a real asyncio.Task."""

    def is_ready(self):
        return True

    async def result(self):
        raise TimeoutError("Utility model call timed out after 180s")


@pytest.mark.asyncio
async def test_a_stalled_background_task_does_not_hang_the_turn():
    agent = _FakeAgent(history=_StalledProviderHistory())
    agent.data[DATA_NAME_TASK] = _StalledTask()

    await OrganizeHistoryWait(agent).execute()

    assert agent.data[DATA_NAME_TASK] is None, "the stalled task must be cleared"
    assert agent.context.log.entries
    assert agent.context.log.entries[-1]["heading"] == "History compression stalled"

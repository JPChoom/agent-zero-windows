"""Tests for helpers.extension.best_effort, the shared decorator used to
stop non-critical extensions from crashing the turn they run in.

This carries real weight: it is applied to every extension fixed in the
"full sweep" pass rather than each hand-rolling its own try/except, so a
bug here is a bug in all of them at once.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from helpers.extension import Extension, best_effort


class _Log:
    def __init__(self):
        self.logs = []

    def log(self, **kw):
        self.logs.append(kw)
        return object()


class _Context:
    def __init__(self):
        self.log = _Log()


class _Agent:
    def __init__(self):
        self.context = _Context()


@pytest.mark.asyncio
async def test_an_exception_does_not_propagate():
    class Boom(Extension):
        @best_effort("Boom")
        async def execute(self, **kwargs):
            raise ValueError("nope")

    # Must not raise.
    await Boom(agent=_Agent()).execute()


@pytest.mark.asyncio
async def test_the_failure_is_logged_as_a_warning_with_the_given_heading():
    class Boom(Extension):
        @best_effort("Skills prompt")
        async def execute(self, **kwargs):
            raise ValueError("nope")

    agent = _Agent()
    await Boom(agent=agent).execute()

    assert len(agent.context.log.logs) == 1
    entry = agent.context.log.logs[0]
    assert entry["type"] == "warning"
    assert entry["heading"] == "Skills prompt error"
    assert "nope" in entry["content"]


@pytest.mark.asyncio
async def test_the_happy_path_is_unaffected():
    calls = []

    class Fine(Extension):
        @best_effort("Fine")
        async def execute(self, **kwargs):
            calls.append(kwargs)
            return "result"

    agent = _Agent()
    result = await Fine(agent=agent).execute(x=1)

    assert result == "result"
    assert calls == [{"x": 1}]
    assert agent.context.log.logs == []


@pytest.mark.asyncio
async def test_arguments_and_kwargs_reach_the_wrapped_function():
    """Extensions are called with arbitrary **kwargs by call_extensions_async
    (loop_data, system_prompt, tool_name, ... depending on extension
    point); the wrapper must be a transparent passthrough."""

    class Echo(Extension):
        @best_effort("Echo")
        async def execute(self, loop_data=None, **kwargs):
            return (loop_data, kwargs)

    agent = _Agent()
    result = await Echo(agent=agent).execute(loop_data="LD", tool_name="t")

    assert result == ("LD", {"tool_name": "t"})


@pytest.mark.asyncio
async def test_no_agent_is_handled_without_raising():
    """Extension.agent can be None (see call_extensions_async's own
    typing); the decorator must not assume it is set."""

    class Boom(Extension):
        @best_effort("Boom")
        async def execute(self, **kwargs):
            raise ValueError("nope")

    # Must not raise, even with no agent to log through.
    await Boom(agent=None).execute()


@pytest.mark.asyncio
async def test_a_broken_log_sink_does_not_mask_the_original_failure():
    """Logging the failure is itself best-effort - a broken logger must
    not become a second, more confusing crash than the one being caught."""

    class BrokenLog:
        def log(self, **kw):
            raise RuntimeError("log sink down")

    class BrokenContext:
        log = BrokenLog()

    class BrokenAgent:
        context = BrokenContext()

    class Boom(Extension):
        @best_effort("Boom")
        async def execute(self, **kwargs):
            raise ValueError("nope")

    # Must not raise, even though logging the failure also fails.
    await Boom(agent=BrokenAgent()).execute()


@pytest.mark.asyncio
async def test_different_extensions_get_their_own_heading():
    """A copy-paste error giving every usage the same heading would make
    the warnings indistinguishable in the log."""

    class First(Extension):
        @best_effort("First thing")
        async def execute(self, **kwargs):
            raise ValueError("a")

    class Second(Extension):
        @best_effort("Second thing")
        async def execute(self, **kwargs):
            raise ValueError("b")

    agent = _Agent()
    await First(agent=agent).execute()
    await Second(agent=agent).execute()

    headings = [e["heading"] for e in agent.context.log.logs]
    assert headings == ["First thing error", "Second thing error"]

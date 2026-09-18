"""A broken promptinclude scan must not break every future prompt build.

This extension runs on the system_prompt extension point, which fires on
every single prepare_prompt call - unlike a message_loop_prompts_after
extension, whose failure only costs one turn. call_extensions_async has
no generic per-extension error handling, so an unguarded exception here
would propagate out and abort system prompt assembly entirely, for every
turn from then on, not just the current one.

It is also the one system_prompt extension that does a live recursive
filesystem scan of the working directory - the same directory
code_execution_tool and text_editor are actively mutating while the agent
runs - which is real, ordinary risk (permission errors, a vanished
project folder, a dropped dev-mode RFC connection), not a hypothetical.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from helpers import debounced
from plugins._promptinclude.extensions.python.system_prompt import (
    _16_promptinclude as pi_mod,
)


@pytest.fixture(autouse=True)
def _clear_debounce_cache():
    # Every test in this module resolves to the same scan_path/config, so
    # without clearing between tests a real scan cached by one test would
    # silently answer a later test's differently-mocked call within the
    # 10s TTL, hiding whatever that test actually meant to exercise.
    debounced.clear()
    yield
    debounced.clear()


class _LogItem:
    pass


class _Log:
    def __init__(self):
        self.logs = []

    def log(self, **kw):
        self.logs.append(kw)
        return _LogItem()


class _Context:
    def __init__(self):
        self.log = _Log()


class _Agent:
    def __init__(self):
        self.context = _Context()


@pytest.mark.asyncio
async def test_a_scan_failure_does_not_raise(monkeypatch):
    """The regression: any exception from _append_includes used to
    propagate straight out of execute(), and from there out of
    call_extensions_async - breaking system prompt assembly for every
    subsequent turn, not just this one."""

    async def boom(*a, **k):
        raise PermissionError("workdir is unreadable")

    monkeypatch.setattr(pi_mod.runtime, "call_development_function", boom)
    monkeypatch.setattr(
        pi_mod.plugins, "get_plugin_config", lambda name, agent=None: {}
    )
    monkeypatch.setattr(pi_mod, "_resolve_workdir", lambda agent: "C:\\somewhere")

    agent = _Agent()
    ext = pi_mod.PromptInclude(agent=agent)  # type: ignore[arg-type]
    system_prompt: list[str] = []

    # Must not raise.
    await ext.execute(system_prompt=system_prompt)

    assert system_prompt == [], "nothing should be appended on failure"


@pytest.mark.asyncio
async def test_the_failure_is_logged():
    async def boom(*a, **k):
        raise PermissionError("workdir is unreadable")

    agent = _Agent()
    ext = pi_mod.PromptInclude(agent=agent)  # type: ignore[arg-type]
    ext._append_includes = boom  # type: ignore[method-assign]

    await ext.execute(system_prompt=[])

    assert agent.context.log.logs, "the failure must be visible somewhere"
    entry = agent.context.log.logs[0]
    assert entry["type"] == "warning"
    assert "unreadable" in entry["content"]


@pytest.mark.asyncio
async def test_a_broken_logger_does_not_mask_the_original_failure():
    """Logging the error is itself best-effort - a broken log call must
    not turn into a second, more confusing crash."""

    class _BrokenLog:
        def log(self, **kw):
            raise RuntimeError("log sink down")

    class _BrokenContext:
        log = _BrokenLog()

    class _BrokenAgent:
        context = _BrokenContext()

    ext = pi_mod.PromptInclude(agent=_BrokenAgent())  # type: ignore[arg-type]

    async def boom(system_prompt):
        raise PermissionError("workdir is unreadable")

    ext._append_includes = boom  # type: ignore[method-assign]

    # Must not raise, even though logging the failure also fails.
    await ext.execute(system_prompt=[])


@pytest.mark.asyncio
async def test_a_working_scan_is_unaffected(monkeypatch):
    """The guard must only catch, not change behaviour on the happy path."""

    def fake_scan(*a, **k):
        # Sync, not async: the real scan_promptinclude_files is a plain
        # sync function run via asyncio.to_thread on the debounced path
        # (see the is_development()/is_windows() branch in _16_promptinclude
        # .py) - an async fake here would hand back an unawaited coroutine
        # instead of a result, silently corrupting the happy path.
        return {"files": [], "skipped_count": 0}

    monkeypatch.setattr(pi_mod, "scan_promptinclude_files", fake_scan)
    monkeypatch.setattr(
        pi_mod.runtime, "call_development_function", lambda func, *a, **k: func(*a, **k)
    )
    monkeypatch.setattr(
        pi_mod.plugins, "get_plugin_config", lambda name, agent=None: {}
    )
    monkeypatch.setattr(pi_mod, "_resolve_workdir", lambda agent: "C:\\somewhere")

    class _WorkingAgent(_Agent):
        def read_prompt(self, name, **k):
            return f"PROMPT:{name}"

    agent = _WorkingAgent()
    ext = pi_mod.PromptInclude(agent=agent)  # type: ignore[arg-type]
    system_prompt: list[str] = []

    await ext.execute(system_prompt=system_prompt)

    assert system_prompt == ["PROMPT:agent.system.promptinclude.md"]
    assert agent.context.log.logs == []

"""call_extensions_sync/async isolate a failing extension by default,
instead of letting one exception abort every other extension still
queued at that call site.

Previously the only way to get isolation was the best_effort decorator,
applied one extension at a time - most extensions across the codebase
had no isolation at all, which drove a 29-file remediation sweep earlier
in this project's history. This makes isolation the dispatcher's own
default, with an explicit opt-out (Extension.FAIL_LOUD = True) for the
handful of extensions whose failure means the turn genuinely cannot
proceed safely: a safety gate, secret masking, core prompt assembly, or
an exception-handler hook itself.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from helpers import extension


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


def _classes(monkeypatch, classes):
    monkeypatch.setattr(extension, "_get_extension_classes", lambda *a, **k: classes)


@pytest.mark.asyncio
async def test_a_failing_extension_does_not_abort_the_others_by_default(monkeypatch):
    calls: list[str] = []

    class Broken(extension.Extension):
        async def execute(self, **kwargs):
            calls.append("broken")
            raise ValueError("boom")

    class Fine(extension.Extension):
        async def execute(self, **kwargs):
            calls.append("fine")

    _classes(monkeypatch, [Broken, Fine])
    agent = _Agent()

    # Must not raise, and Fine must still run despite Broken failing first.
    await extension.call_extensions_async("some_point", agent=agent)

    assert calls == ["broken", "fine"]


def test_a_failing_sync_extension_does_not_abort_the_others_by_default(monkeypatch):
    calls: list[str] = []

    class Broken(extension.Extension):
        def execute(self, **kwargs):
            calls.append("broken")
            raise ValueError("boom")

    class Fine(extension.Extension):
        def execute(self, **kwargs):
            calls.append("fine")

    _classes(monkeypatch, [Broken, Fine])
    agent = _Agent()

    extension.call_extensions_sync("some_point", agent=agent)

    assert calls == ["broken", "fine"]


@pytest.mark.asyncio
async def test_the_failure_is_logged_not_silent(monkeypatch):
    class Broken(extension.Extension):
        async def execute(self, **kwargs):
            raise ValueError("boom")

    _classes(monkeypatch, [Broken])
    agent = _Agent()

    await extension.call_extensions_async("some_point", agent=agent)

    assert agent.context.log.logs, "the failure must be visible somewhere"
    entry = agent.context.log.logs[0]
    assert entry["type"] == "warning"
    assert "boom" in entry["content"]
    assert "Broken" in entry["heading"]


@pytest.mark.asyncio
async def test_a_broken_log_sink_does_not_mask_the_original_failure(monkeypatch):
    """Logging the failure is itself best-effort - a broken log call must
    not turn into a second, more confusing crash."""

    class _BrokenLog:
        def log(self, **kw):
            raise RuntimeError("log sink down")

    class _BrokenContext:
        log = _BrokenLog()

    class _BrokenAgent:
        context = _BrokenContext()

    class Broken(extension.Extension):
        async def execute(self, **kwargs):
            raise ValueError("boom")

    _classes(monkeypatch, [Broken])

    # Must not raise, even though logging the failure also fails.
    await extension.call_extensions_async("some_point", agent=_BrokenAgent())


@pytest.mark.asyncio
async def test_a_fail_loud_extension_still_aborts_the_call_site(monkeypatch):
    """The explicit opt-out: a security-critical extension (a masking
    control, a safety gate, core prompt assembly) must keep propagating
    its own exception rather than being silently swallowed."""
    calls: list[str] = []

    class Critical(extension.Extension):
        FAIL_LOUD = True

        async def execute(self, **kwargs):
            calls.append("critical")
            raise ValueError("must not be swallowed")

    class NeverReached(extension.Extension):
        async def execute(self, **kwargs):
            calls.append("never")

    _classes(monkeypatch, [Critical, NeverReached])
    agent = _Agent()

    with pytest.raises(ValueError, match="must not be swallowed"):
        await extension.call_extensions_async("some_point", agent=agent)

    assert calls == ["critical"], "a FAIL_LOUD extension must still stop the call site"


def test_a_fail_loud_sync_extension_still_aborts_the_call_site(monkeypatch):
    class Critical(extension.Extension):
        FAIL_LOUD = True

        def execute(self, **kwargs):
            raise ValueError("must not be swallowed")

    _classes(monkeypatch, [Critical])
    agent = _Agent()

    with pytest.raises(ValueError, match="must not be swallowed"):
        extension.call_extensions_sync("some_point", agent=agent)


@pytest.mark.asyncio
async def test_the_default_extension_is_not_fail_loud():
    """The base class's own default must be isolation, not fail-loud -
    every extension is isolated unless it explicitly opts out."""
    assert extension.Extension.FAIL_LOUD is False


@pytest.mark.asyncio
async def test_a_working_extension_is_unaffected(monkeypatch):
    """The isolation wrapper must only catch, not change behaviour on the
    happy path."""
    results = []

    class Working(extension.Extension):
        async def execute(self, **kwargs):
            results.append(kwargs.get("value"))

    _classes(monkeypatch, [Working])
    agent = _Agent()

    await extension.call_extensions_async("some_point", agent=agent, value=42)

    assert results == [42]
    assert agent.context.log.logs == []


# Regression guard: these are the extensions whose failure means the turn
# genuinely cannot proceed safely (a safety gate, secret masking, core
# prompt assembly, an exception-handler hook) - if isolation's default
# flip ever loses one of these opt-outs, the failure mode is silent
# (a masking bug that leaks a secret, a safety gate that stops blocking),
# not a loud test failure, so it is worth pinning explicitly.
_EXPECTED_FAIL_LOUD = [
    ("extensions.python.system_prompt._10_main_prompt", "MainPrompt"),
    ("extensions.python.tool_execute_after._10_mask_secrets", "MaskToolSecrets"),
    ("extensions.python.tool_execute_before._10_unmask_secrets", "UnmaskToolSecrets"),
    ("extensions.python.tool_execute_before._20_block_parallel_recursion", "BlockParallelRecursion"),
    ("extensions.python.util_model_call_before._10_mask_secrets", "MaskToolSecrets"),
    ("extensions.python.tool_execute_before._95_audit_log_capture", "AuditLogCapture"),
    ("extensions.python.tool_execute_after._95_audit_log", "AuditLog"),
    (
        "extensions.python._functions.agent.Agent.handle_exception.end._40_handle_intervention_exception",
        "HandleInterventionException",
    ),
    (
        "extensions.python._functions.agent.Agent.handle_exception.end._50_handle_repairable_exception",
        "HandleRepairableException",
    ),
    (
        "extensions.python._functions.agent.Agent.handle_exception.end._90_handle_critical_exception",
        "HandleCriticalException",
    ),
    (
        "plugins._error_retry.extensions.python._functions.agent.Agent.handle_exception.end._80_retry_critical_exception",
        "RetryCriticalException",
    ),
]


@pytest.mark.parametrize("module_name, class_name", _EXPECTED_FAIL_LOUD)
def test_known_security_critical_extensions_stay_fail_loud(module_name, class_name):
    import importlib

    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    assert cls.FAIL_LOUD is True, (
        f"{module_name}.{class_name} must stay FAIL_LOUD - its failure "
        "means the turn cannot proceed safely, so isolating it by "
        "default would be a silent security/correctness regression"
    )

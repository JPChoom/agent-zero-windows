"""Tests for the global kill switch (helpers/kill_switch.py, Phase E of
the hand-off roadmap): the flag-file-backed trip/reset state, the API
handler, both defense-in-depth check points (_safety_policy's command
policy extension and code_execution_tool.py directly), and the fail-
closed startup self-test.
"""

import asyncio

import pytest

from helpers import kill_switch
from helpers.errors import RepairableException
from api.kill_switch import KillSwitch
from plugins._safety_policy.extensions.python.tool_execute_before._05_command_policy import (
    SafetyCommandPolicy,
)
from plugins._code_execution.tools.code_execution_tool import CodeExecution
from extensions.python.startup_migration._20_safety_policy_failclosed_selftest import (
    _check_fail_closed_invariants,
)


@pytest.fixture(autouse=True)
def _redirect_flag_file(tmp_path, monkeypatch):
    path = tmp_path / ".kill_switch"
    monkeypatch.setattr(kill_switch, "get_flag_path", lambda: str(path))
    return path


# ------------------------------------------------------------------
# helpers/kill_switch.py
# ------------------------------------------------------------------

def test_not_tripped_by_default():
    assert kill_switch.is_tripped() is False
    assert kill_switch.get_reason() == ""


def test_trip_and_is_tripped():
    kill_switch.trip("testing")

    assert kill_switch.is_tripped() is True
    assert kill_switch.get_reason() == "testing"


def test_trip_with_no_reason():
    kill_switch.trip()

    assert kill_switch.is_tripped() is True
    assert kill_switch.get_reason() == ""


def test_reset_clears_tripped_state():
    kill_switch.trip("testing")
    kill_switch.reset()

    assert kill_switch.is_tripped() is False


def test_reset_when_not_tripped_does_not_raise():
    kill_switch.reset()  # must not raise even though nothing to remove

    assert kill_switch.is_tripped() is False


def test_flag_file_survives_across_calls(_redirect_flag_file):
    kill_switch.trip("persisted")

    # A fresh check (as if a new process started) reads the same file.
    assert _redirect_flag_file.exists()
    assert kill_switch.is_tripped() is True


def test_denial_message_includes_reason_when_present():
    kill_switch.trip("safety drill")

    message = kill_switch.denial_message()

    assert "kill switch" in message.lower()
    assert "safety drill" in message


def test_denial_message_omits_reason_when_absent():
    kill_switch.trip()

    message = kill_switch.denial_message()

    assert "Reason:" not in message


# ------------------------------------------------------------------
# api/kill_switch.py
# ------------------------------------------------------------------

class _FakeApp:
    pass


@pytest.mark.asyncio
async def test_api_status_action_does_not_change_state():
    handler = KillSwitch(app=_FakeApp(), thread_lock=None)

    result = await handler.process({"action": "status"}, request=None)

    assert result == {"tripped": False, "reason": ""}


@pytest.mark.asyncio
async def test_api_trip_action_trips_and_returns_state():
    handler = KillSwitch(app=_FakeApp(), thread_lock=None)

    result = await handler.process({"action": "trip", "reason": "manual test"}, request=None)

    assert result == {"tripped": True, "reason": "manual test"}
    assert kill_switch.is_tripped() is True


@pytest.mark.asyncio
async def test_api_reset_action_resets_state():
    kill_switch.trip("was tripped")
    handler = KillSwitch(app=_FakeApp(), thread_lock=None)

    result = await handler.process({"action": "reset"}, request=None)

    assert result == {"tripped": False, "reason": ""}


@pytest.mark.asyncio
async def test_api_defaults_to_status_when_action_missing():
    kill_switch.trip("preexisting")
    handler = KillSwitch(app=_FakeApp(), thread_lock=None)

    result = await handler.process({}, request=None)

    assert result == {"tripped": True, "reason": "preexisting"}


@pytest.mark.asyncio
async def test_api_rejects_unknown_action():
    handler = KillSwitch(app=_FakeApp(), thread_lock=None)

    response = await handler.process({"action": "sabotage"}, request=None)

    assert response.status_code == 400


# ------------------------------------------------------------------
# defense-in-depth check #1: _safety_policy's command policy extension
# ------------------------------------------------------------------

class _FakeContext:
    id = "ctx-1"


class _FakeAgentConfig:
    profile = "agent0"


class _FakeAgent:
    def __init__(self):
        self.context = _FakeContext()
        self.agent_name = "A0"
        self.config = _FakeAgentConfig()


@pytest.mark.asyncio
async def test_command_policy_denies_when_kill_switch_tripped_even_if_policy_disabled(monkeypatch):
    from plugins._safety_policy.extensions.python.tool_execute_before import _05_command_policy

    # enforce_policy=False would normally let everything through - the
    # kill switch must still deny, proving it's an independent control.
    monkeypatch.setattr(
        _05_command_policy, "get_config", lambda agent: {"enforce_policy": False}
    )
    kill_switch.trip("halted")

    ext = SafetyCommandPolicy(agent=_FakeAgent())

    with pytest.raises(RepairableException) as exc_info:
        await ext.execute(tool_name="code_execution_tool", tool_args={"runtime": "terminal", "code": "echo hi"})

    assert "kill switch" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_command_policy_allows_normal_commands_when_not_tripped(monkeypatch):
    from plugins._safety_policy.extensions.python.tool_execute_before import _05_command_policy

    monkeypatch.setattr(
        _05_command_policy, "get_config", lambda agent: {"enforce_policy": False}
    )

    ext = SafetyCommandPolicy(agent=_FakeAgent())

    await ext.execute(tool_name="code_execution_tool", tool_args={"runtime": "terminal", "code": "echo hi"})
    # must not raise


# ------------------------------------------------------------------
# defense-in-depth check #2: code_execution_tool.py directly
# ------------------------------------------------------------------

class _FakeExecAgent:
    async def handle_intervention(self):
        return None


def _make_tool(**args):
    return CodeExecution(
        agent=_FakeExecAgent(),
        name="code_execution_tool",
        method=None,
        args=args,
        message="",
        loop_data=None,
    )


@pytest.mark.asyncio
async def test_code_execution_tool_denies_terminal_when_tripped():
    kill_switch.trip("halted")
    tool = _make_tool(runtime="terminal", code="echo hi")

    response = await tool.execute()

    assert "kill switch" in response.message.lower()


@pytest.mark.asyncio
async def test_code_execution_tool_denies_python_when_tripped():
    kill_switch.trip("halted")
    tool = _make_tool(runtime="python", code="print(1)")

    response = await tool.execute()

    assert "kill switch" in response.message.lower()


@pytest.mark.asyncio
async def test_code_execution_tool_denies_nodejs_when_tripped():
    kill_switch.trip("halted")
    tool = _make_tool(runtime="nodejs", code="console.log(1)")

    response = await tool.execute()

    assert "kill switch" in response.message.lower()


@pytest.mark.asyncio
async def test_code_execution_tool_allows_output_runtime_when_tripped():
    """"output" reads a previous session's output - doesn't execute
    anything new, so the kill-switch guard must not short-circuit it.
    _FakeExecAgent is too minimal to run get_terminal_output()'s real
    session lookup to completion, so this only proves the guard was
    bypassed (no kill-switch denial), not that the deeper flow succeeds -
    that's exercised by this repo's existing code_execution_tool tests."""
    kill_switch.trip("halted")
    tool = _make_tool(runtime="output", session=0)

    try:
        response = await tool.execute()
    except Exception as exc:
        assert "kill switch" not in str(exc).lower()
    else:
        assert "kill switch" not in response.message.lower()


# ------------------------------------------------------------------
# fail-closed startup self-test
# ------------------------------------------------------------------

def test_selftest_passes_against_real_config():
    ok, problems = _check_fail_closed_invariants()

    assert ok is True
    assert problems == []


def test_selftest_catches_a_flipped_enforce_policy_default(monkeypatch):
    import plugins._safety_policy.helpers.config as safety_config

    monkeypatch.setattr(
        safety_config,
        "get_config",
        lambda agent: {
            "enforce_policy": False,  # simulates a regression
            "custom_deny_patterns": [],
            "approval_tier_categories": set(),
            "approval_timeout_seconds": 300,
        },
    )

    ok, problems = _check_fail_closed_invariants()

    assert ok is False
    assert any("enforce_policy" in p for p in problems)


def test_selftest_catches_a_broken_approval_timeout(monkeypatch):
    import plugins._safety_policy.helpers.config as safety_config

    monkeypatch.setattr(
        safety_config,
        "get_config",
        lambda agent: {
            "enforce_policy": True,
            "custom_deny_patterns": [],
            "approval_tier_categories": set(),
            "approval_timeout_seconds": -5,  # simulates a regression
        },
    )

    ok, problems = _check_fail_closed_invariants()

    assert ok is False
    assert any("approval_timeout_seconds" in p for p in problems)

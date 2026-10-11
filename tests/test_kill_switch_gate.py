"""The kill switch stops every acting tool (enforcement audit E2, E3)."""

from __future__ import annotations

import asyncio
import types

import pytest

from helpers import extension, kill_switch
from helpers.errors import RepairableException

import importlib

gate_mod = importlib.import_module("extensions.python.tool_execute_before._01_kill_switch")


class _Agent:
    agent_name = "A0"
    number = 0

    def __init__(self):
        self.context = types.SimpleNamespace(id="ctx", data={}, log=None)


@pytest.fixture
def only_gate(monkeypatch):
    monkeypatch.setattr(
        extension, "_get_extension_classes",
        lambda point, agent=None, **kw: [gate_mod.KillSwitchGate] if point == "tool_execute_before" else [],
    )


def _call(tool_name, tool_args):
    return asyncio.run(extension.call_extensions_async(
        "tool_execute_before", agent=_Agent(), tool_name=tool_name, tool_args=tool_args,
    ))


ACTING = [
    ("browser", {"action": "navigate", "url": "https://example.com"}),
    ("text_editor", {"action": "write", "path": "a.txt", "content": "x"}),
    ("code_execution_tool", {"runtime": "terminal", "code": "dir"}),
    ("code_execution_remote", {"runtime": "python", "code": "print(1)"}),
    ("computer_use_remote", {"action": "click"}),
    ("blender.execute_blender_code", {"code": "print(1)"}),  # an MCP tool
    ("scheduler", {"action": "create_scheduled_task"}),
    ("memory_save", {"text": "x"}),
]

STILL_ALLOWED = [
    ("response", {"text": "I am halted."}),
    ("text_editor", {"action": "read", "path": "a.txt"}),
    ("windows_info", {"query": "system"}),
    ("code_execution_tool", {"runtime": "output", "session": 0}),
    ("code_execution_remote", {"runtime": "reset", "session": 0}),
    ("search_engine", {"query": "x"}),
]


@pytest.mark.parametrize(("tool_name", "tool_args"), ACTING)
def test_tripped_switch_refuses_acting_tools(only_gate, monkeypatch, tool_name, tool_args):
    monkeypatch.setattr(kill_switch, "is_tripped", lambda: True)
    with pytest.raises(RepairableException, match="kill_switch"):
        _call(tool_name, tool_args)


@pytest.mark.parametrize(("tool_name", "tool_args"), STILL_ALLOWED)
def test_tripped_switch_allows_read_only_tools(only_gate, monkeypatch, tool_name, tool_args):
    monkeypatch.setattr(kill_switch, "is_tripped", lambda: True)
    _call(tool_name, tool_args)


@pytest.mark.parametrize(("tool_name", "tool_args"), ACTING)
def test_switch_off_allows_everything(only_gate, monkeypatch, tool_name, tool_args):
    monkeypatch.setattr(kill_switch, "is_tripped", lambda: False)
    _call(tool_name, tool_args)


def test_remote_execution_checks_the_switch_itself(monkeypatch):
    # Second layer, inside the tool: holds even if the core gate were removed.
    from plugins._a0_connector.tools import code_execution_remote as remote

    monkeypatch.setattr(kill_switch, "is_tripped", lambda: True)
    monkeypatch.setattr(kill_switch, "denial_message", lambda: "KILL SWITCH")

    def no_targets(*args, **kwargs):
        raise AssertionError("must not look for a CLI to send to")

    monkeypatch.setattr(remote, "remote_tool_sids_for_context", no_targets)
    agent = types.SimpleNamespace(context=types.SimpleNamespace(id="ctx"))
    tool = remote.CodeExecutionRemote(agent, "code_execution_remote", None,
                                      {"runtime": "terminal", "code": "dir"}, "", None)
    result = asyncio.run(tool.execute())
    assert result.message == "KILL SWITCH"


@pytest.mark.asyncio
async def test_remote_execution_passes_the_safety_floor(monkeypatch):
    from plugins._safety_policy.extensions.python.tool_execute_before import _05_command_policy as policy_mod
    from plugins._safety_policy.helpers import audit_log, policy

    monkeypatch.setattr(
        extension, "_get_extension_classes",
        lambda point, agent=None, **kw: [policy_mod.SafetyCommandPolicy] if point == "tool_execute_before" else [],
    )
    monkeypatch.setattr(policy_mod, "get_config", lambda agent: {
        "enforce_policy": True, "custom_deny_patterns": [],
        "approval_tier_categories": list(policy._APPROVAL_TIER_DEFAULT_CATEGORIES),
        "approval_timeout_seconds": 5, "enable_network_destination_allowlist": False,
        "network_destination_allowlist": [],
    })
    monkeypatch.setattr(audit_log, "append_denial", lambda record: None)
    monkeypatch.setattr(policy_mod.kill_switch, "is_tripped", lambda: False)
    persistence = r"reg add HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v x /d calc.exe"

    for args in (
        {"runtime": "terminal", "code": persistence},
        {"runtime": "input", "keyboard": persistence},
        {"runtime": "input", "code": persistence},
    ):
        with pytest.raises(RepairableException, match="safety_policy"):
            await extension.call_extensions_async(
                "tool_execute_before", agent=_Agent(), tool_name="code_execution_remote", tool_args=args,
            )
    await extension.call_extensions_async(
        "tool_execute_before", agent=_Agent(), tool_name="code_execution_remote",
        tool_args={"runtime": "terminal", "code": "dir"},
    )

"""Every tool that sends text to a shell passes the command safety floor.

Enforcement audit finding E1 (2026-10-11): the `input` tool types its
`keyboard` text into the same terminal session as code_execution_tool, but
the floor only inspected calls named code_execution_tool, so a denied
command sent through `input` ran unchecked in Auto/Bypass mode.
"""

from __future__ import annotations

import types

import pytest

from helpers import extension, parallel_tools
from helpers.errors import RepairableException
from plugins._code_execution.tools import code_execution_tool, input as input_tool
from plugins._safety_policy.extensions.python.tool_execute_before import _05_command_policy as policy_mod

PERSISTENCE = r"reg add HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v x /d calc.exe"


class _Log:
    def log(self, **kw):
        return types.SimpleNamespace(id="log", kvps=kw.get("kvps", {}), update=lambda **k: None)


class _Agent:
    agent_name = "A0"
    number = 0

    def __init__(self):
        self.context = types.SimpleNamespace(id="ctx", log=_Log(), data={}, get_data=lambda k: None)
        self.loop_data = types.SimpleNamespace(current_tool=None)
        self.config = types.SimpleNamespace(profile="")
        self.history = []

    async def handle_intervention(self):
        return None

    def hist_add_tool_result(self, *args, **kwargs):
        self.history.append(args)

    def get_tool(self, name, method, args, message, loop_data, **kwargs):
        if name == "input":
            return input_tool.Input(self, name, method, args, message, loop_data)
        return None


@pytest.fixture
def floor(monkeypatch):
    """Only the safety floor runs, with the shipped policy enforced."""
    from plugins._safety_policy.helpers import audit_log, policy

    monkeypatch.setattr(
        extension, "_get_extension_classes",
        lambda point, agent=None, **kw: [policy_mod.SafetyCommandPolicy] if point == "tool_execute_before" else [],
    )
    monkeypatch.setattr(policy_mod, "get_config", lambda agent: {
        "enforce_policy": True,
        "custom_deny_patterns": [],
        "approval_tier_categories": list(policy._APPROVAL_TIER_DEFAULT_CATEGORIES),
        "approval_timeout_seconds": 5,
        "enable_network_destination_allowlist": False,
        "network_destination_allowlist": [],
    })
    monkeypatch.setattr(audit_log, "append_denial", lambda record: None)
    monkeypatch.setattr(policy_mod.kill_switch, "is_tripped", lambda: False)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "tool_args"),
    [
        ("code_execution_tool", {"runtime": "terminal", "code": PERSISTENCE}),
        ("code_execution_tool", {"runtime": "input", "code": PERSISTENCE}),
        ("input", {"keyboard": PERSISTENCE, "session": 0}),
    ],
)
async def test_denied_command_is_refused_on_every_shell_route(floor, tool_name, tool_args):
    with pytest.raises(RepairableException, match="safety_policy"):
        await extension.call_extensions_async(
            "tool_execute_before", agent=_Agent(), tool_name=tool_name, tool_args=tool_args,
        )


@pytest.mark.asyncio
async def test_harmless_input_still_passes(floor):
    await extension.call_extensions_async(
        "tool_execute_before", agent=_Agent(), tool_name="input", tool_args={"keyboard": "Y", "session": 0},
    )


@pytest.mark.asyncio
async def test_refused_input_never_reaches_the_terminal(floor, monkeypatch):
    # The real dispatch order (gate, then tool) as parallel workers run it.
    sent = []

    async def fake_execute(self, **kwargs):
        sent.append(kwargs.get("code"))
        return types.SimpleNamespace(message="ran", break_loop=False, additional=None)

    monkeypatch.setattr(code_execution_tool.CodeExecution, "execute", fake_execute)
    import helpers.mcp_handler as mcp_helper

    monkeypatch.setattr(mcp_helper.MCPConfig, "get_instance", classmethod(
        lambda cls: types.SimpleNamespace(get_tool=lambda agent, name: None)
    ))

    with pytest.raises(RepairableException):
        await parallel_tools.execute_tool_call(_Agent(), "input", {"keyboard": PERSISTENCE, "session": 0})
    assert sent == []

    await parallel_tools.execute_tool_call(_Agent(), "input", {"keyboard": "Y", "session": 0})
    assert sent == ["Y"]

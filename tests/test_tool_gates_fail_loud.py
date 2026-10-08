"""Tool gates must refuse through the real extension dispatcher.

The dispatcher isolates extensions by default: an exception an extension
raises is logged and swallowed (helpers/extension.py). The gates below refuse
by raising, so each must set FAIL_LOUD = True or its refusal becomes a
warning and the tool runs anyway. The gate unit tests call execute()
directly and cannot see this, so these go through call_extensions_async.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from helpers import extension
from helpers.errors import RepairableException
from plugins._permissions.extensions.python.tool_execute_before import _06_permissions as gate_mod
from plugins._permissions.helpers import rules
from plugins._safety_policy.extensions.python.tool_execute_before import _05_command_policy as policy_mod

ROOT = Path(__file__).resolve().parents[1]
GATE_POINTS = ("tool_execute_before", "tool_execute_after")
RAISES_TO_BLOCK = re.compile(r"raise\s+(RepairableException|InterventionException)\b")


class _Log:
    def log(self, **kw):
        return type("Item", (), {"kvps": kw.get("kvps", {}), "update": lambda self, **k: None})()


class _Agent:
    agent_name = "A0"
    number = 0

    def __init__(self):
        self.context = type("Ctx", (), {"id": "ctx", "log": _Log(), "data": {}})()


@pytest.fixture(autouse=True)
def _no_audit(monkeypatch):
    from plugins._safety_policy.helpers import audit_log

    monkeypatch.setattr(audit_log, "append_denial", lambda record: None)


def _only(monkeypatch, *classes):
    monkeypatch.setattr(extension, "_get_extension_classes", lambda point, agent=None, **kw: list(classes))


def _cfg(mode):
    return {"mode": mode, "ruleset": rules.Ruleset.from_config({}), "approval_timeout_seconds": 5,
            "audit_decisions": False}


SET_CALL = {"tool_name": "windows_setting", "tool_args": {"action": "set", "setting": "file_extensions", "value": "hide"}}


@pytest.mark.asyncio
async def test_plan_mode_refusal_reaches_the_caller(monkeypatch):
    _only(monkeypatch, gate_mod.PermissionGate)
    monkeypatch.setattr(gate_mod, "get_config", lambda agent: _cfg("plan"))
    with pytest.raises(RepairableException, match="Plan mode is on"):
        await extension.call_extensions_async("tool_execute_before", agent=_Agent(), **SET_CALL)


@pytest.mark.asyncio
async def test_a_deny_click_reaches_the_caller(monkeypatch):
    _only(monkeypatch, gate_mod.PermissionGate)
    monkeypatch.setattr(gate_mod, "get_config", lambda agent: _cfg("manual"))

    async def declined(*a, **k):
        raise RepairableException("[permissions] The user declined windows_setting.")

    monkeypatch.setattr(gate_mod.ask, "request_approval", declined)
    with pytest.raises(RepairableException, match="declined"):
        await extension.call_extensions_async("tool_execute_before", agent=_Agent(), **SET_CALL)


@pytest.mark.asyncio
async def test_the_kill_switch_refusal_reaches_the_caller(monkeypatch):
    _only(monkeypatch, policy_mod.SafetyCommandPolicy)
    monkeypatch.setattr(policy_mod.kill_switch, "is_tripped", lambda: True)
    monkeypatch.setattr(policy_mod.kill_switch, "denial_message", lambda: "KILL SWITCH")
    with pytest.raises(RepairableException, match="KILL SWITCH"):
        await extension.call_extensions_async(
            "tool_execute_before", agent=_Agent(),
            tool_name="code_execution_tool", tool_args={"runtime": "terminal", "code": "dir"},
        )


@pytest.mark.asyncio
async def test_an_allowed_call_still_passes(monkeypatch):
    _only(monkeypatch, gate_mod.PermissionGate)
    monkeypatch.setattr(gate_mod, "get_config", lambda agent: _cfg("plan"))
    await extension.call_extensions_async(
        "tool_execute_before", agent=_Agent(),
        tool_name="windows_setting", tool_args={"action": "get", "setting": "file_extensions"},
    )


def _gate_files():
    roots = [ROOT / "extensions" / "python"] + sorted((ROOT / "plugins").glob("*/extensions/python"))
    for root in roots:
        for point in GATE_POINTS:
            folder = root / point
            if folder.is_dir():
                yield from sorted(folder.glob("*.py"))


def test_every_tool_gate_that_refuses_by_raising_is_fail_loud():
    files = list(_gate_files())
    assert files, "no tool gate extensions found"
    missing = [
        str(f.relative_to(ROOT))
        for f in files
        if RAISES_TO_BLOCK.search(f.read_text(encoding="utf-8")) and "FAIL_LOUD = True" not in f.read_text(encoding="utf-8")
    ]
    assert missing == [], (
        "These tool gates refuse by raising but are isolated by the dispatcher, "
        f"so their refusal is swallowed and the tool runs. Set FAIL_LOUD = True: {missing}"
    )

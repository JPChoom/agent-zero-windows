"""Tests for the permission gate extension.

The gate sits in front of every tool call, so its failure modes matter as
much as its successes: a broken config must not wedge the agent, an
unanswered prompt must not hang forever, and the ordering that keeps the
safety floor above the permission mode must hold.
"""

from __future__ import annotations

import asyncio

import pytest

from helpers.errors import RepairableException
from plugins._permissions.extensions.python.tool_execute_before import (
    _06_permissions as gate_mod,
)
from plugins._permissions.helpers import rules


class _Log:
    def __init__(self):
        self.items = []

    def log(self, **kw):
        item = type("Item", (), {"kvps": kw.get("kvps", {}), "update": lambda **k: None})()
        self.items.append(kw)
        return item


class _Context:
    id = "ctx"

    def __init__(self):
        self.log = _Log()


class _Agent:
    agent_name = "A0"

    def __init__(self):
        self.context = _Context()


def _gate():
    return gate_mod.PermissionGate(agent=_Agent())  # type: ignore[arg-type]


def _cfg(mode="auto", **kw):
    return {
        "mode": mode,
        "ruleset": rules.Ruleset.from_config(kw.pop("rules", {})),
        "approval_timeout_seconds": kw.pop("timeout", 300),
        "audit_decisions": False,
        **kw,
    }


@pytest.fixture(autouse=True)
def _no_audit(monkeypatch):
    """Never touch the real hash-chained audit log from a test."""
    from plugins._safety_policy.helpers import audit_log

    monkeypatch.setattr(audit_log, "append_denial", lambda record: None)


# ------------------------------------------------------------------
# Allow and deny
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_allowed_calls_pass_through_silently(monkeypatch):
    monkeypatch.setattr(gate_mod, "get_config", lambda agent=None: _cfg("auto"))
    # No exception means the tool proceeds.
    assert await _gate().execute(tool_name="code_execution_tool",
                                 tool_args={"code": "ls"}) is None


@pytest.mark.asyncio
async def test_denied_calls_raise_repairable(monkeypatch):
    monkeypatch.setattr(
        gate_mod, "get_config",
        lambda agent=None: _cfg("auto", rules={"deny": ["code_execution_tool(*rm -rf*)"]}),
    )
    with pytest.raises(RepairableException) as exc:
        await _gate().execute(tool_name="code_execution_tool", tool_args={"code": "rm -rf /"})
    assert "permissions" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_plan_mode_denial_explains_the_mode(monkeypatch):
    """A generic refusal would leave the agent guessing; it should say the
    mode is the reason and that the user can change it."""
    monkeypatch.setattr(gate_mod, "get_config", lambda agent=None: _cfg("plan"))
    with pytest.raises(RepairableException) as exc:
        await _gate().execute(tool_name="text_editor", tool_args={"action": "write"})
    text = str(exc.value).lower()
    assert "plan mode" in text and "switch modes" in text


# ------------------------------------------------------------------
# Tools the gate must not block
# ------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["response", "call_subordinate"])
async def test_turn_ending_tools_are_never_gated(monkeypatch, tool):
    """Gating `response` would stop the agent from being able to say it
    needs permission - a deadlock rather than a safeguard."""
    monkeypatch.setattr(gate_mod, "get_config", lambda agent=None: _cfg("plan"))
    assert await _gate().execute(tool_name=tool, tool_args={"text": "hi"}) is None


@pytest.mark.asyncio
async def test_missing_tool_name_is_ignored(monkeypatch):
    monkeypatch.setattr(gate_mod, "get_config", lambda agent=None: _cfg("plan"))
    assert await _gate().execute(tool_name="", tool_args={}) is None


@pytest.mark.asyncio
async def test_broken_config_fails_open(monkeypatch):
    """A config error must not wedge every tool call: the user could not
    then reach the settings UI to fix it."""
    def boom(agent=None):
        raise RuntimeError("config is corrupt")

    monkeypatch.setattr(gate_mod, "get_config", boom)
    assert await _gate().execute(tool_name="code_execution_tool",
                                 tool_args={"code": "ls"}) is None


# ------------------------------------------------------------------
# The ask flow
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approval_lets_the_call_proceed(monkeypatch):
    monkeypatch.setattr(gate_mod, "get_config", lambda agent=None: _cfg("manual"))

    async def approve(fut):
        await asyncio.sleep(0)
        fut.set_result(True)

    registered = {}

    def fake_register(approval_id):
        fut = asyncio.get_event_loop().create_future()
        registered["id"] = approval_id
        asyncio.ensure_future(approve(fut))
        return fut

    monkeypatch.setattr(gate_mod.approval_registry, "register", fake_register)
    assert await _gate().execute(tool_name="code_execution_tool",
                                 tool_args={"code": "ls"}) is None
    assert registered["id"]


@pytest.mark.asyncio
async def test_refusal_raises_and_tells_the_agent_not_to_retry(monkeypatch):
    monkeypatch.setattr(gate_mod, "get_config", lambda agent=None: _cfg("manual"))

    def fake_register(approval_id):
        fut = asyncio.get_event_loop().create_future()
        fut.set_result(False)
        return fut

    monkeypatch.setattr(gate_mod.approval_registry, "register", fake_register)
    with pytest.raises(RepairableException) as exc:
        await _gate().execute(tool_name="code_execution_tool", tool_args={"code": "ls"})
    assert "do not retry" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_unanswered_prompt_times_out_as_denied(monkeypatch):
    """An approval nobody answers must not hold the turn open forever."""
    monkeypatch.setattr(
        gate_mod, "get_config", lambda agent=None: _cfg("manual", timeout=0.05)
    )
    cleaned = []
    monkeypatch.setattr(
        gate_mod.approval_registry, "register",
        lambda approval_id: asyncio.get_event_loop().create_future(),
    )
    monkeypatch.setattr(
        gate_mod.approval_registry, "cleanup", lambda approval_id: cleaned.append(approval_id)
    )
    with pytest.raises(RepairableException) as exc:
        await _gate().execute(tool_name="code_execution_tool", tool_args={"code": "ls"})
    assert "treated as denied" in str(exc.value).lower()
    # The pending future must be released, or the registry leaks per prompt.
    assert cleaned


@pytest.mark.asyncio
async def test_prompt_offers_a_rule_that_would_prevent_it_recurring(monkeypatch):
    monkeypatch.setattr(gate_mod, "get_config", lambda agent=None: _cfg("manual"))

    def fake_register(approval_id):
        fut = asyncio.get_event_loop().create_future()
        fut.set_result(True)
        return fut

    monkeypatch.setattr(gate_mod.approval_registry, "register", fake_register)
    agent = _Agent()
    gate = gate_mod.PermissionGate(agent=agent)  # type: ignore[arg-type]
    await gate.execute(tool_name="code_execution_tool", tool_args={"code": "git status"})

    logged = agent.context.log.items[0]
    kvps = logged["kvps"]
    assert logged["type"] == "permissions_approval_request"
    # The offered rule must actually match the call it came from.
    rule = rules.Rule.parse(kvps["suggested_rule"])
    assert rule.matches("code_execution_tool", "git status")
    assert rules.Rule.parse(kvps["suggested_tool_rule"]).matches(
        "code_execution_tool", "anything"
    )


# ------------------------------------------------------------------
# Ordering against the safety floor
# ------------------------------------------------------------------

def test_gate_runs_after_the_safety_policy():
    """Filename ordering is the mechanism: _05 (safety) must get its veto
    before _06 (permissions), so a permissive mode cannot disable a safety
    control."""
    import pathlib

    safety = pathlib.Path(
        "plugins/_safety_policy/extensions/python/tool_execute_before"
    )
    perms = pathlib.Path(
        "plugins/_permissions/extensions/python/tool_execute_before"
    )
    safety_names = sorted(p.name for p in safety.glob("_*.py"))
    perms_names = sorted(p.name for p in perms.glob("_*.py"))
    assert safety_names and perms_names
    assert max(safety_names) < min(perms_names)

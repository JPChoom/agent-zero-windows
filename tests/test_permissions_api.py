"""Tests for the permissions API endpoints.

Both endpoints back a button, so the cases that matter are the ones where
a silent failure would mislead the user: a mode that appears to change but
was not saved, or an "always allow" that resolves the prompt without
storing the rule, leaving them to be asked the same question again.
"""

from __future__ import annotations

import pytest

from api import permissions_mode as mode_api
from api import permissions_respond as respond_api
from plugins._permissions.helpers import rules


def _mode_handler():
    return mode_api.PermissionsMode(app=None, thread_lock=None)  # type: ignore[arg-type]


def _respond_handler():
    return respond_api.PermissionsRespond(app=None, thread_lock=None)  # type: ignore[arg-type]


# ------------------------------------------------------------------
# Mode endpoint
# ------------------------------------------------------------------

class _Req:
    remote_addr = "127.0.0.1"
    headers: dict = {}


@pytest.fixture
def per_chat(monkeypatch):
    """Isolated in-memory mode state with default 'manual', 4h bypass."""
    from plugins._permissions.helpers import mode_state

    mode_state.clear_all()
    monkeypatch.setattr(mode_state, "default_mode", lambda: "manual")
    monkeypatch.setattr(mode_state, "bypass_hours", lambda: 4.0)
    monkeypatch.setattr(mode_api.PermissionsMode, "_project", lambda self, ctxid: "")
    mode_api.bypass_throttle.__init__()
    yield mode_state
    mode_state.clear_all()


@pytest.mark.asyncio
async def test_reading_returns_default_mode_and_the_full_list(per_chat, monkeypatch):
    monkeypatch.setattr(mode_api.bypass_lock, "is_set", lambda: True)
    result = await _mode_handler().process({"ctxid": "c1"}, _Req())  # type: ignore[arg-type]
    assert result["ok"] is True and result["mode"] == "manual"
    assert [m["id"] for m in result["modes"]] == list(rules.MODES)
    # Every mode needs a label, description and color for the selector.
    assert all(m["label"] and m["description"] and m["color"] for m in result["modes"])


@pytest.mark.asyncio
async def test_mode_is_per_chat(per_chat):
    result = await _mode_handler().process({"ctxid": "c1", "mode": "plan"}, _Req())  # type: ignore[arg-type]
    assert result["ok"] is True and result["mode"] == "plan"
    other = await _mode_handler().process({"ctxid": "c2"}, _Req())  # type: ignore[arg-type]
    assert other["mode"] == "manual"


@pytest.mark.asyncio
async def test_unknown_mode_is_refused(per_chat):
    result = await _mode_handler().process({"ctxid": "c1", "mode": "turbo"}, _Req())  # type: ignore[arg-type]
    assert result["ok"] is False and "turbo" in result["error"]


@pytest.mark.asyncio
async def test_setting_a_mode_needs_a_chat(per_chat):
    result = await _mode_handler().process({"mode": "plan"}, _Req())  # type: ignore[arg-type]
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_bypass_refused_without_a_configured_password(per_chat, monkeypatch):
    monkeypatch.setattr(mode_api.bypass_lock, "is_set", lambda: False)
    result = await _mode_handler().process({"ctxid": "c1", "mode": "bypass"}, _Req())  # type: ignore[arg-type]
    assert result["ok"] is False and result.get("needs_setup")
    assert per_chat.get_mode("c1")["mode"] == "manual"


@pytest.mark.asyncio
async def test_bypass_refused_with_wrong_password_and_rate_limited(per_chat, monkeypatch):
    monkeypatch.setattr(mode_api.bypass_lock, "is_set", lambda: True)
    monkeypatch.setattr(mode_api.bypass_lock, "verify", lambda pw: pw == "right-password")
    monkeypatch.setattr(mode_api.access_control, "audit", lambda *a, **k: None)
    for _ in range(mode_api.bypass_throttle.MAX_FAILURES):
        r = await _mode_handler().process({"ctxid": "c1", "mode": "bypass", "password": "nope"}, _Req())  # type: ignore[arg-type]
        assert r["ok"] is False
    # Locked out now - even the right password is refused for a while.
    r = await _mode_handler().process({"ctxid": "c1", "mode": "bypass", "password": "right-password"}, _Req())  # type: ignore[arg-type]
    assert r["ok"] is False and "later" in r["error"]
    assert per_chat.get_mode("c1")["mode"] == "manual"


@pytest.mark.asyncio
async def test_bypass_unlocks_with_right_password_and_has_a_deadline(per_chat, monkeypatch):
    monkeypatch.setattr(mode_api.bypass_lock, "is_set", lambda: True)
    monkeypatch.setattr(mode_api.bypass_lock, "verify", lambda pw: pw == "right-password")
    monkeypatch.setattr(mode_api.access_control, "audit", lambda *a, **k: None)
    r = await _mode_handler().process({"ctxid": "c1", "mode": "bypass", "password": "right-password"}, _Req())  # type: ignore[arg-type]
    assert r["ok"] is True and r["mode"] == "bypass" and r["bypass_until"] > 0


# ------------------------------------------------------------------
# Respond endpoint
# ------------------------------------------------------------------

@pytest.fixture
def resolved(monkeypatch):
    calls = []
    monkeypatch.setattr(
        respond_api.approval_registry, "resolve",
        lambda approval_id, approved: calls.append((approval_id, approved)) or True,
    )
    return calls


@pytest.mark.asyncio
async def test_approve_resolves_the_pending_call(resolved):
    result = await _respond_handler().process(
        {"approval_id": "abc", "approved": True}, None  # type: ignore[arg-type]
    )
    assert result["approved"] is True and result["resolved"] is True
    assert resolved == [("abc", True)]


@pytest.mark.asyncio
async def test_deny_resolves_as_refused(resolved):
    await _respond_handler().process(
        {"approval_id": "abc", "approved": False}, None  # type: ignore[arg-type]
    )
    assert resolved == [("abc", False)]


@pytest.mark.asyncio
async def test_always_allow_saves_the_rule(monkeypatch, resolved):
    saved = []
    monkeypatch.setattr(
        respond_api.perm_config, "add_rule",
        lambda kind, text: saved.append((kind, text)) or text,
    )
    result = await _respond_handler().process(
        {"approval_id": "abc", "approved": True,
         "remember": "code_execution_tool(git status*)"},
        None,  # type: ignore[arg-type]
    )
    assert saved == [("allow", "code_execution_tool(git status*)")]
    assert result["remembered"] == "code_execution_tool(git status*)"


@pytest.mark.asyncio
async def test_rule_is_saved_before_the_call_is_released(monkeypatch):
    """Resolving first would let the tool run while the write is still in
    flight, so a failure to persist would be invisible."""
    order = []
    monkeypatch.setattr(
        respond_api.perm_config, "add_rule",
        lambda kind, text: order.append("saved") or text,
    )
    monkeypatch.setattr(
        respond_api.approval_registry, "resolve",
        lambda approval_id, approved: order.append("resolved") or True,
    )
    await _respond_handler().process(
        {"approval_id": "abc", "approved": True, "remember": "text_editor"},
        None,  # type: ignore[arg-type]
    )
    assert order == ["saved", "resolved"]


@pytest.mark.asyncio
async def test_a_bad_rule_is_reported_but_still_approves(monkeypatch, resolved):
    """The user pressed Allow; the call should proceed. But they must be
    told the rule did not save, or they will believe they have stopped
    being asked."""
    def boom(kind, text):
        raise rules.RuleError("cannot parse")

    monkeypatch.setattr(respond_api.perm_config, "add_rule", boom)
    result = await _respond_handler().process(
        {"approval_id": "abc", "approved": True, "remember": "((("},
        None,  # type: ignore[arg-type]
    )
    assert result["approved"] is True and result["resolved"] is True
    assert result["remembered"] == "" and "could not save rule" in result["error"]


@pytest.mark.asyncio
async def test_deny_never_saves_a_rule(monkeypatch, resolved):
    """A remembered rule on a denial would allow exactly what was refused."""
    saved = []
    monkeypatch.setattr(
        respond_api.perm_config, "add_rule", lambda k, t: saved.append(t) or t
    )
    await _respond_handler().process(
        {"approval_id": "abc", "approved": False, "remember": "text_editor"},
        None,  # type: ignore[arg-type]
    )
    assert saved == []


@pytest.mark.asyncio
async def test_missing_approval_id_is_not_treated_as_resolved(monkeypatch):
    monkeypatch.setattr(
        respond_api.approval_registry, "resolve",
        lambda approval_id, approved: True,
    )
    result = await _respond_handler().process({"approved": True}, None)  # type: ignore[arg-type]
    assert result["resolved"] is False

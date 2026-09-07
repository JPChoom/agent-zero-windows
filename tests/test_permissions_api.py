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

@pytest.mark.asyncio
async def test_reading_returns_current_mode_and_the_full_list(monkeypatch):
    monkeypatch.setattr(
        mode_api.perm_config, "get_config", lambda *a, **k: {"mode": "manual"}
    )
    result = await _mode_handler().process({}, None)  # type: ignore[arg-type]
    assert result["ok"] is True and result["mode"] == "manual"
    assert [m["id"] for m in result["modes"]] == list(rules.MODES)
    # Every mode needs a label and description for the selector.
    assert all(m["label"] and m["description"] for m in result["modes"])


@pytest.mark.asyncio
async def test_setting_a_mode_persists_it(monkeypatch):
    saved = {}
    monkeypatch.setattr(
        mode_api.perm_config, "set_mode",
        lambda m: saved.setdefault("mode", m) or m,
    )
    result = await _mode_handler().process({"mode": "plan"}, None)  # type: ignore[arg-type]
    assert result == {"ok": True, "mode": "plan"}
    assert saved["mode"] == "plan"


@pytest.mark.asyncio
async def test_unknown_mode_is_refused_rather_than_stored(monkeypatch):
    def boom(m):
        raise ValueError(f"unknown mode {m!r}")

    monkeypatch.setattr(mode_api.perm_config, "set_mode", boom)
    result = await _mode_handler().process({"mode": "turbo"}, None)  # type: ignore[arg-type]
    assert result["ok"] is False and "turbo" in result["error"]


@pytest.mark.asyncio
async def test_save_failure_is_reported_not_swallowed(monkeypatch):
    """The selector rolls back on ok:false; silently returning success
    would leave the UI showing a mode the server never stored."""
    def boom(m):
        raise OSError("disk full")

    monkeypatch.setattr(mode_api.perm_config, "set_mode", boom)
    result = await _mode_handler().process({"mode": "plan"}, None)  # type: ignore[arg-type]
    assert result["ok"] is False and "disk full" in result["error"]


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

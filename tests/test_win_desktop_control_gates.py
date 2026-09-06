"""Tests for the safety gates on plugins/_win_desktop/tools/desktop_control.py.

Synthetic input is the one surface in this plugin that can act on the user's
machine, and it bypasses _safety_policy entirely - that plugin inspects
terminal command *text*, and a synthetic click carries none. So the gates
here are the only thing standing between the agent and the desktop, and each
is asserted to actually block, not merely to exist:

1. control_enabled is opt-in and off by default,
2. a tripped kill switch refuses regardless of config,
3. accepted actions are written to the hash-chained audit log *before*
   execution, so an action that hangs or crashes still leaves a record.

`_dispatch` is stubbed throughout, so no test can reach real SendInput.
"""

from __future__ import annotations

import pytest

from plugins._win_desktop.tools import desktop_control as dc


class _DummyContext:
    id = "ctx-test"


class _DummyAgent:
    agent_name = "A0"
    context = _DummyContext()

    async def handle_intervention(self, *a, **k):
        return None


def _tool(**args):
    tool = dc.DesktopControl(
        agent=_DummyAgent(),  # type: ignore[arg-type]
        name="desktop_control",
        method=None,
        args=args,
        message="",
        loop_data=None,
    )
    return tool


@pytest.fixture(autouse=True)
def _no_real_input(monkeypatch):
    """Hard stop: nothing in this module may reach the OS."""
    performed: list[tuple] = []
    for name in ("move", "click", "scroll", "type_text", "press_keys"):
        monkeypatch.setattr(
            dc.input_control,
            name,
            lambda *a, _n=name, **k: performed.append((_n, a, k)),
        )
    # Window targeting also touches the live desktop, and reading the real
    # foreground window would make results depend on what is on screen.
    monkeypatch.setattr(
        dc.input_control,
        "focus_window",
        lambda title, *a, **k: performed.append(("focus_window", (title,), {}))
        or f"[{title}]",
    )
    monkeypatch.setattr(
        dc.input_control, "get_foreground_window", lambda: (1, "Ambient Window")
    )
    return performed


@pytest.fixture(autouse=True)
def audited(monkeypatch):
    """Capture audit records instead of appending them.

    autouse, not opt-in: the tool audits before dispatching, so any test
    that reaches a known action would otherwise append to the real
    usr/audit_log.jsonl. That log is hash-chained user data - polluting it
    from a test run is not something a later cleanup can undo without
    breaking the chain.
    """
    records: list[dict] = []

    async def fake_append(record):
        records.append(record)
        return record

    monkeypatch.setattr(dc.audit_log, "append_record", fake_append)
    return records


def _allow(monkeypatch, control_enabled=True, tripped=False):
    monkeypatch.setattr(
        dc.capture,
        "get_config",
        lambda agent=None: {
            "capture_enabled": True,
            "capture_max_edge": 1280,
            "capture_jpeg_quality": 60,
            "control_enabled": control_enabled,
        },
    )
    monkeypatch.setattr(dc.kill_switch, "is_tripped", lambda: tripped)
    monkeypatch.setattr(dc.kill_switch, "denial_message", lambda: "KILL SWITCH ACTIVE")


# ------------------------------------------------------------------
# Gate 1 - opt-in
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disabled_by_default_blocks_every_action(monkeypatch, _no_real_input, audited):
    _allow(monkeypatch, control_enabled=False)
    for action, args in [
        ("click", {"x": 1, "y": 1}),
        ("type", {"text": "rm -rf"}),
        ("key", {"keys": "enter"}),
        ("move", {"x": 1, "y": 1}),
        ("scroll", {"x": 1, "y": 1, "amount": 1}),
    ]:
        response = await _tool(action=action, **args).execute(action=action, **args)
        assert "disabled" in response.message.lower()
    assert _no_real_input == []
    # Nothing refused should be audited as performed.
    assert audited == []


# ------------------------------------------------------------------
# Gate 2 - kill switch
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kill_switch_overrides_enabled_config(monkeypatch, _no_real_input, audited):
    _allow(monkeypatch, control_enabled=True, tripped=True)
    response = await _tool(action="click", x=5, y=5).execute(action="click", x=5, y=5)
    assert "KILL SWITCH ACTIVE" in response.message
    assert _no_real_input == []
    assert audited == []


# ------------------------------------------------------------------
# Gate 3 - audit
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_accepted_action_is_audited_with_details(monkeypatch, _no_real_input, audited):
    _allow(monkeypatch)
    await _tool(action="click", x=12, y=34).execute(action="click", x=12, y=34)
    assert len(audited) == 1
    record = audited[0]
    assert record["tool"] == "desktop_control"
    assert record["action"] == "click"
    assert record["arguments"]["x"] == 12
    assert record["context"] == "ctx-test"


@pytest.mark.asyncio
async def test_audit_happens_even_when_the_action_then_fails(monkeypatch, audited):
    """A record must survive an action that raises - otherwise the most
    interesting failures are the ones that leave no trace."""
    _allow(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("driver exploded")

    monkeypatch.setattr(dc.input_control, "click", boom)
    response = await _tool(action="click", x=1, y=1).execute(action="click", x=1, y=1)
    assert "failed" in response.message.lower()
    assert len(audited) == 1


# ------------------------------------------------------------------
# Dispatch and validation
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_action_is_rejected(monkeypatch, _no_real_input, audited):
    _allow(monkeypatch)
    response = await _tool(action="format_c_drive").execute(action="format_c_drive")
    assert "unknown action" in response.message.lower()
    assert _no_real_input == []
    assert audited == []


@pytest.mark.asyncio
async def test_each_action_reaches_its_handler(monkeypatch, _no_real_input, audited):
    _allow(monkeypatch)
    cases = [
        (dict(action="move", x=1, y=2), "move"),
        (dict(action="click", x=1, y=2), "click"),
        (dict(action="scroll", x=1, y=2, amount=-3), "scroll"),
        (dict(action="type", text="hello"), "type_text"),
        (dict(action="key", keys="ctrl+s"), "press_keys"),
    ]
    for args, expected in cases:
        _no_real_input.clear()
        await _tool(**args).execute(**args)
        assert _no_real_input and _no_real_input[0][0] == expected


@pytest.mark.asyncio
async def test_missing_required_arguments_are_reported_not_raised(monkeypatch, _no_real_input):
    _allow(monkeypatch)
    for args in [
        dict(action="click"),                  # no x/y
        dict(action="scroll", x=1, y=1),       # no amount
        dict(action="type"),                   # no text
        dict(action="key"),                    # no keys
    ]:
        response = await _tool(**args).execute(**args)
        assert "invalid request" in response.message.lower()
    assert _no_real_input == []


@pytest.mark.asyncio
async def test_non_integer_coordinates_are_reported(monkeypatch, _no_real_input):
    _allow(monkeypatch)
    response = await _tool(action="click", x="left-ish", y=5).execute(
        action="click", x="left-ish", y=5
    )
    assert "invalid request" in response.message.lower()
    assert _no_real_input == []


@pytest.mark.asyncio
async def test_tests_never_touch_the_real_audit_log(monkeypatch, _no_real_input, audited):
    """Guard against the autouse fixture being weakened later: exercising
    every action must leave the on-disk log untouched."""
    import os

    from helpers import audit_log as real_audit_log

    path = real_audit_log.get_audit_log_path()
    before = os.path.getsize(path) if os.path.exists(path) else 0

    _allow(monkeypatch)
    for args in [
        dict(action="click", x=1, y=1),
        dict(action="type", text="x"),
        dict(action="key", keys="enter"),
    ]:
        await _tool(**args).execute(**args)

    after = os.path.getsize(path) if os.path.exists(path) else 0
    assert after == before, "a test wrote to the real audit log"
    assert len(audited) == 3


@pytest.mark.asyncio
async def test_success_message_prompts_verification(monkeypatch, _no_real_input, audited):
    """The model should confirm with a screenshot rather than assume the
    click landed where it intended."""
    _allow(monkeypatch)
    response = await _tool(action="click", x=1, y=1).execute(action="click", x=1, y=1)
    assert "desktop_screenshot" in response.message


# ------------------------------------------------------------------
# Window targeting
# ------------------------------------------------------------------
#
# Input goes wherever focus is. A live test that launched Notepad and typed
# into it appended the text to a pre-existing, unsaved Notepad document,
# because launching an application neither guarantees focus nor a new
# window. These cover the targeting added in response.

@pytest.mark.asyncio
async def test_named_window_is_focused_before_acting(monkeypatch, _no_real_input, audited):
    _allow(monkeypatch)
    await _tool(action="type", window="Notepad", text="hi").execute(
        action="type", window="Notepad", text="hi"
    )
    assert _no_real_input[0] == ("focus_window", ("Notepad",), {})
    assert _no_real_input[1][0] == "type_text"


@pytest.mark.asyncio
async def test_unfocusable_window_refuses_without_typing(monkeypatch, _no_real_input, audited):
    """An ambiguous or missing target must abort, not fall back to
    whatever happens to be focused."""
    _allow(monkeypatch)

    def refuse(title, *a, **k):
        raise dc.input_control.InputError(f"3 windows match {title!r}")

    monkeypatch.setattr(dc.input_control, "focus_window", refuse)
    response = await _tool(action="type", window="Notepad", text="x").execute(
        action="type", window="Notepad", text="x"
    )
    assert "invalid request" in response.message.lower()
    assert _no_real_input == []
    # Refused before it could act, so nothing is recorded as performed.
    assert audited == []


@pytest.mark.asyncio
async def test_audit_records_where_the_input_actually_went(monkeypatch, _no_real_input, audited):
    _allow(monkeypatch)
    await _tool(action="type", window="Notepad", text="x").execute(
        action="type", window="Notepad", text="x"
    )
    assert audited[0]["target_window"] == "[Notepad]"
    assert audited[0]["targeted_explicitly"] is True


@pytest.mark.asyncio
async def test_audit_records_ambient_focus_when_no_window_named(monkeypatch, _no_real_input, audited):
    _allow(monkeypatch)
    await _tool(action="type", text="x").execute(action="type", text="x")
    assert audited[0]["target_window"] == "Ambient Window"
    assert audited[0]["targeted_explicitly"] is False


@pytest.mark.asyncio
async def test_untargeted_typing_is_flagged_in_the_result(monkeypatch, _no_real_input, audited):
    """The model should be told its text went somewhere unverified rather
    than reading a bare success."""
    _allow(monkeypatch)
    response = await _tool(action="type", text="x").execute(action="type", text="x")
    assert "whatever had focus" in response.message
    assert "Ambient Window" in response.message


@pytest.mark.asyncio
async def test_targeted_typing_is_not_flagged(monkeypatch, _no_real_input, audited):
    _allow(monkeypatch)
    response = await _tool(action="type", window="N", text="x").execute(
        action="type", window="N", text="x"
    )
    assert "whatever had focus" not in response.message


@pytest.mark.asyncio
async def test_focus_action_requires_a_window(monkeypatch, _no_real_input, audited):
    _allow(monkeypatch)
    response = await _tool(action="focus").execute(action="focus")
    assert "invalid request" in response.message.lower()

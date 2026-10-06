"""computer_use: hard limits, ownership-based approvals, and permission
classification; messaging-channel permission caps. No real driver runs -
driver calls are faked."""

from __future__ import annotations

import pytest

from helpers.errors import RepairableException
from plugins._computer_use.helpers import policy
from plugins._permissions.helpers import config as perm_config
from plugins._permissions.helpers import rules


# -- hard limits --------------------------------------------------------------

@pytest.mark.parametrize("proc", ["consent.exe", "CredentialUIBroker.exe", "KeePassXC.exe", "1Password.exe"])
@pytest.mark.parametrize("action", ["inspect", "screenshot", "click", "type"])
def test_secret_windows_are_off_limits_even_for_reading(proc, action):
    assert policy.refusal(action, proc)


@pytest.mark.parametrize("proc", ["WindowsTerminal.exe", "cmd.exe", "powershell.exe", "pwsh.exe"])
def test_typing_into_terminals_is_refused_but_reading_them_is_not(proc):
    assert policy.refusal("type", proc)
    assert policy.refusal("hotkey", proc, keys=["ctrl", "v"])
    assert not policy.refusal("inspect", proc)


@pytest.mark.parametrize("keys", [["win", "l"], "ctrl+alt+delete", ["Control", "Alt", "Del"], "win+r", ["ctrl", "shift", "escape"]])
def test_lock_logoff_and_run_box_hotkeys_are_never_sent(keys):
    assert policy.refusal("hotkey", "notepad.exe", keys=keys)


def test_ordinary_hotkeys_pass_and_closing_ones_are_risky():
    assert not policy.refusal("hotkey", "notepad.exe", keys=["ctrl", "s"])
    assert policy.risky_hotkey("alt+f4")
    assert not policy.risky_hotkey(["ctrl", "s"])


@pytest.mark.parametrize("label", ["Password", "Enter PIN", "One-time code", "Recovery key", "Card number"])
def test_secret_fields_are_never_typed_into(label):
    assert policy.refusal("type", "chrome.exe", element_label=label)
    assert policy.refusal("set_value", "chrome.exe", element_label=label)


def test_normal_fields_pass():
    assert not policy.refusal("type", "notepad.exe", element_label="Text editor")


# -- permission classification -------------------------------------------------

@pytest.mark.parametrize("action", ["apps", "windows", "inspect", "screenshot", "status"])
def test_look_actions_are_reads(action):
    assert rules.classify("computer_use", {"action": action}) == "read"
    assert rules.decide("computer_use", {"action": action}, "plan").decision == "allow"


@pytest.mark.parametrize("action", ["click", "type", "launch", "hotkey"])
def test_input_actions_execute_and_plan_mode_refuses_them(action):
    assert rules.classify("computer_use", {"action": action}) == "execute"
    assert rules.decide("computer_use", {"action": action}, "plan").decision == "deny"
    assert rules.decide("computer_use", {"action": action}, "manual").decision == "ask"


# -- tool gates (driver faked) -------------------------------------------------

class _Log:
    def __init__(self):
        self.items = []

    def log(self, **kw):
        self.items.append(kw)
        return None


class _Ctx:
    def __init__(self):
        self.id = "ctx-test"
        self.data = {}
        self.log = _Log()


class _Agent:
    agent_name = "A0"

    def __init__(self):
        self.context = _Ctx()

    async def handle_intervention(self):
        return None


@pytest.fixture
def tool(monkeypatch):
    from plugins._computer_use.tools import computer_use as mod

    calls, approvals, audits = [], [], []

    async def fake_call(agent, tool_name, args):
        calls.append((tool_name, args))
        if tool_name == "list_apps":
            return {"apps": [{"pid": 100, "name": "notepad.exe", "running": True, "windows": [{}]}]}
        if tool_name == "list_windows":
            names = {100: "Notepad.exe", 200: "Notepad.exe", 300: "WindowsTerminal.exe"}
            return {"windows": [{"pid": args.get("pid"), "app_name": names.get(args.get("pid"), "app.exe")}]}
        if tool_name == "launch_app":
            return {"pid": 200, "windows": []}
        return {"summary": "ok"}

    async def fake_approval(agent, tool_name, args, reason, mode, timeout, offer_rules=True):
        approvals.append(reason)

    async def fake_audit(record):
        audits.append(record)

    monkeypatch.setattr(mod.driver, "call", fake_call)
    monkeypatch.setattr(mod.driver, "get_config", lambda agent=None: {**mod.driver.DEFAULTS, "control_enabled": True})
    monkeypatch.setattr(mod.audit_log, "append_record", fake_audit)
    monkeypatch.setattr(mod.kill_switch, "is_tripped", lambda: False)
    import plugins._permissions.helpers.ask as ask_mod
    monkeypatch.setattr(ask_mod, "request_approval", fake_approval)
    monkeypatch.setattr(
        perm_config, "get_config",
        lambda agent=None: {"mode": "auto", "ruleset": rules.Ruleset(), "approval_timeout_seconds": 5},
    )

    agent = _Agent()
    t = mod.ComputerUse(agent=agent, name="computer_use", method=None, args={}, message="", loop_data=None)
    return t, calls, approvals, audits


@pytest.mark.asyncio
async def test_input_is_refused_while_control_is_disabled(tool, monkeypatch):
    t, calls, _, _ = tool
    from plugins._computer_use.tools import computer_use as mod
    monkeypatch.setattr(mod.driver, "get_config", lambda agent=None: dict(mod.driver.DEFAULTS))
    resp = await t.execute(action="type", pid=200, text="x")
    assert "disabled" in resp.message and not calls


@pytest.mark.asyncio
async def test_typing_into_a_window_the_agent_did_not_open_asks_first(tool):
    t, calls, approvals, audits = tool
    await t.execute(action="type", pid=100, text="hello")
    assert approvals and "not opened by the agent" in approvals[0]
    assert audits and audits[0]["owned"] is False
    assert ("type_text", ) == tuple(c[0] for c in calls if c[0] == "type_text")


@pytest.mark.asyncio
async def test_a_freshly_launched_app_is_owned_and_needs_no_extra_approval(tool):
    t, calls, approvals, _ = tool
    resp = await t.execute(action="launch", app="notepad")
    assert "New process" in resp.message
    launch_args = next(a for name, a in calls if name == "launch_app")
    assert launch_args["creates_new_application_instance"] is True
    await t.execute(action="type", pid=200, text="hello")
    assert approvals == []


@pytest.mark.asyncio
async def test_attaching_to_an_already_running_app_is_not_owned(tool):
    t, calls, approvals, _ = tool
    import plugins._computer_use.tools.computer_use as mod

    async def attach(agent, tool_name, args):
        if tool_name == "list_apps":
            return {"apps": [{"pid": 100, "name": "notepad.exe", "running": True}]}
        if tool_name == "launch_app":
            return {"pid": 100}
        return {"windows": [{"pid": 100, "app_name": "Notepad.exe"}], "summary": "ok"}

    mod.driver.call = attach
    resp = await t.execute(action="launch", app="notepad")
    assert "ALREADY running" in resp.message
    assert not t._owned(100)


@pytest.mark.asyncio
async def test_foreground_delivery_asks_even_for_owned_windows(tool):
    t, _, approvals, _ = tool
    await t.execute(action="launch", app="notepad")
    await t.execute(action="key", pid=200, key="enter", delivery="foreground")
    assert approvals and "foreground" in approvals[0]


@pytest.mark.asyncio
async def test_terminal_input_is_refused_before_any_approval(tool):
    t, calls, approvals, _ = tool
    with pytest.raises(RepairableException):
        await t.execute(action="type", pid=300, text="del /s /q C:\\")
    assert not approvals and not any(c[0] == "type_text" for c in calls)


@pytest.mark.asyncio
async def test_close_only_ends_agent_opened_apps(tool):
    t, calls, _, _ = tool
    with pytest.raises(RepairableException):
        await t.execute(action="close", pid=100)
    await t.execute(action="launch", app="notepad")
    await t.execute(action="close", pid=200)
    assert any(c[0] == "kill_app" for c in calls)


# -- messaging channel caps ----------------------------------------------------

class _ChanCtx:
    def __init__(self, data):
        self.data = data


@pytest.mark.parametrize("data,channel", [
    ({"telegram_chat_id": 5}, "telegram"),
    ({"wa_chat_id": "x"}, "whatsapp"),
    ({"email_sender": "a@example.com"}, "email"),
    ({"discord_channel_id": 9}, "discord"),
    ({"slack_channel_id": "C1"}, "slack"),
    ({}, ""),
])
def test_channel_detection(data, channel):
    assert perm_config.channel_of(_ChanCtx(data)) == channel


def test_caps_take_the_safer_mode_and_never_allow_bypass():
    assert rules.safer_mode("bypass", "manual") == "manual"
    assert rules.safer_mode("plan", "manual") == "plan"
    assert perm_config.channel_cap({}, "telegram") == "manual"
    assert perm_config.channel_cap({"channel_mode_caps": {"telegram": "bypass"}}, "telegram") == "auto"
    assert perm_config.channel_cap({"channel_mode_caps": {"slack": "plan"}}, "slack") == "plan"

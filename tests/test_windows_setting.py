"""windows_setting: the fixed catalog, value validation, undo information,
audit/kill switch, wallpaper path confinement and permission class. Runs
against a fake backend - the real registry is only read, never written."""

from __future__ import annotations

import sys

import pytest

from plugins._windows_intel.helpers import settings_catalog as cat

POWERCFG_LIST = """Existing Power Schemes (* Active)
-----------------------------------
Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced) *
Power Scheme GUID: 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c  (High performance)
"""


class FakeBackend(cat.Backend):
    def __init__(self, build=26100):
        self.reg = {}
        self.events = []
        self.build = build
        self.active = "381b4222-f694-41f0-9685-ff5bb260df2e"
        self.wall = ""

    def reg_get(self, path, name):
        return self.reg.get((path, name))

    def reg_set_dword(self, path, name, value):
        self.reg[(path, name)] = value

    def broadcast(self, area):
        self.events.append(("broadcast", area))

    def explorer_refresh(self):
        self.events.append(("explorer",))

    def powercfg(self, *args):
        if args == ("/list",):
            return 0, POWERCFG_LIST.replace(" *", "").replace(f"{self.active}  (", f"{self.active}  (", 1).replace(
                f"{self.active}  (Balanced)", f"{self.active}  (Balanced) *").replace(
                f"{self.active}  (High performance)", f"{self.active}  (High performance) *")
        if args[0] == "/setactive":
            self.active = args[1]
            return 0, ""
        return 1, "bad"

    def wallpaper_get(self):
        return self.wall

    def wallpaper_set(self, path):
        self.wall = path
        return True

    def windows_build(self):
        return self.build


@pytest.fixture
def tool(monkeypatch):
    from plugins._windows_intel.tools import windows_setting as mod

    audits = []

    async def fake_audit(record):
        audits.append(record)

    monkeypatch.setattr(mod.audit_log, "append_record", fake_audit)
    monkeypatch.setattr(mod.kill_switch, "is_tripped", lambda: False)
    t = mod.WindowsSetting(agent=type("A", (), {"context": type("C", (), {"id": "c"})()})(),
                           name="windows_setting", method=None, args={}, message="", loop_data=None)
    t.backend = FakeBackend()
    return t, mod, audits


@pytest.mark.asyncio
async def test_theme_round_trip_reports_previous_value_and_undo(tool):
    t, _, audits = tool
    assert (await t.execute(action="get", setting="theme")).message == "theme: Windows default (not set)"
    msg = (await t.execute(action="set", setting="theme", value="Dark")).message
    assert "-> dark" in msg and "value=Windows default (not set)" in msg
    assert t.backend.reg[(cat._PERSONALIZE, "AppsUseLightTheme")] == 0
    assert t.backend.reg[(cat._PERSONALIZE, "SystemUsesLightTheme")] == 0
    assert ("broadcast", "ImmersiveColorSet") in t.backend.events
    msg = (await t.execute(action="set", setting="theme", value="light")).message
    assert "dark -> light" in msg and "value=dark" in msg
    assert audits[-1] == {"tool": "windows_setting", "action": "set", "setting": "theme", "from": "dark", "to": "light", "context": "c"}


@pytest.mark.asyncio
@pytest.mark.parametrize("setting,value,key,expect", [
    ("file_extensions", "show", "HideFileExt", 0),
    ("file_extensions", "hide", "HideFileExt", 1),
    ("hidden_files", "show", "Hidden", 1),
    ("hidden_files", "hide", "Hidden", 2),
    ("taskbar_alignment", "left", "TaskbarAl", 0),
])
async def test_explorer_settings_write_exactly_their_value(tool, setting, value, key, expect):
    t, _, _ = tool
    await t.execute(action="set", setting=setting, value=value)
    assert t.backend.reg == {(cat._ADVANCED, key): expect}


@pytest.mark.asyncio
async def test_values_outside_the_allowed_set_are_refused(tool):
    t, _, audits = tool
    msg = (await t.execute(action="set", setting="theme", value="purple")).message
    assert "must be one of: light, dark" in msg and t.backend.reg == {} and audits == []
    assert "unknown setting" in (await t.execute(action="set", setting="firewall", value="off")).message
    assert "does not take" in (await t.execute(action="set", setting="theme", value="dark", path="HKLM")).message


@pytest.mark.asyncio
async def test_taskbar_alignment_needs_windows_11(tool):
    t, _, _ = tool
    t.backend.build = 19045
    assert "needs Windows 11" in (await t.execute(action="set", setting="taskbar_alignment", value="left")).message
    assert t.backend.reg == {}


@pytest.mark.asyncio
async def test_power_plan_switches_only_between_existing_plans(tool):
    t, _, _ = tool
    assert (await t.execute(action="get", setting="power_plan")).message == "power_plan: Balanced"
    msg = (await t.execute(action="set", setting="power_plan", value="high performance")).message
    assert "Balanced -> High performance" in msg
    assert t.backend.active == "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
    assert "must be one of" in (await t.execute(action="set", setting="power_plan", value="Ultimate")).message


@pytest.mark.asyncio
async def test_list_shows_every_setting(tool):
    t, _, _ = tool
    out = (await t.execute(action="list")).message
    for name in cat.CATALOG:
        assert name in out


@pytest.mark.asyncio
async def test_set_is_refused_while_the_kill_switch_is_tripped(tool, monkeypatch):
    t, mod, _ = tool
    monkeypatch.setattr(mod.kill_switch, "is_tripped", lambda: True)
    monkeypatch.setattr(mod.kill_switch, "denial_message", lambda: "KILL SWITCH")
    assert (await t.execute(action="set", setting="theme", value="dark")).message == "KILL SWITCH"
    assert t.backend.reg == {}


def test_wallpaper_must_be_an_image_inside_the_allowed_folders(tmp_path):
    allowed, outside = tmp_path / "work", tmp_path / "elsewhere"
    allowed.mkdir()
    outside.mkdir()
    (allowed / "pic.png").write_bytes(b"x")
    (allowed / "notes.txt").write_text("x")
    (outside / "pic.png").write_bytes(b"x")
    assert cat.check_wallpaper_path(str(allowed / "pic.png"), [allowed]) == (allowed / "pic.png").resolve()
    for bad, why in [(outside / "pic.png", "inside"), (allowed / "notes.txt", ".png"),
                     (allowed / "missing.png", "does not exist"), (allowed / ".." / "elsewhere" / "pic.png", "inside")]:
        with pytest.raises(cat.SettingError, match=why):
            cat.check_wallpaper_path(str(bad), [allowed])


def test_permission_classes():
    from plugins._permissions.helpers import rules

    assert rules.decide("windows_setting", {"action": "list"}, "plan").decision == "allow"
    assert rules.decide("windows_setting", {"action": "get", "setting": "theme"}, "plan").decision == "allow"
    assert rules.decide("windows_setting", {"action": "set", "setting": "theme", "value": "dark"}, "plan").decision == "deny"
    assert rules.decide("windows_setting", {"action": "set", "setting": "theme", "value": "dark"}, "manual").decision == "ask"


@pytest.mark.skipif(sys.platform != "win32", reason="reads the real settings")
def test_every_setting_can_be_read_on_this_machine():
    backend = cat.Backend()
    for spec in cat.CATALOG.values():
        if spec.available(backend):
            continue
        assert spec.get(backend)
        assert spec.choices(backend)

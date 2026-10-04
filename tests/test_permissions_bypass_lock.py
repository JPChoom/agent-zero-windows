"""Per-chat in-memory permission modes, the Bypass password, the agent-side
guard against touching the lock, and the allowlist endpoint's lockout guard."""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from plugins._permissions.helpers import bypass_lock, mode_state

# Captured at import, before tests/conftest.py's autouse fixture swaps it.
_REAL_DEFAULT_MODE = mode_state.default_mode


@pytest.fixture
def state(monkeypatch):
    mode_state.clear_all()
    monkeypatch.setattr(mode_state, "default_mode", lambda: "manual")
    monkeypatch.setattr(mode_state, "bypass_hours", lambda: 2.0)
    yield mode_state
    mode_state.clear_all()


# -- mode_state ------------------------------------------------------------

def test_new_chat_starts_at_default(state):
    assert state.get_mode("new-chat")["mode"] == "manual"


def test_restart_resets_everything(state):
    state.set_mode("c1", "auto")
    state.clear_all()  # what a process restart amounts to: memory is gone
    assert state.get_mode("c1")["mode"] == "manual"


def test_project_switch_resets_to_default(state):
    state.set_mode("c1", "auto", project="alpha")
    assert state.get_mode("c1", project="alpha")["mode"] == "auto"
    assert state.get_mode("c1", project="beta")["mode"] == "manual"
    assert state.get_mode("c1", project="alpha")["mode"] == "manual"  # stays reset


def test_bypass_expires_and_reports_it_once(state):
    s = state.set_mode("c1", "bypass", now=1000.0)
    assert s["mode"] == "bypass" and s["bypass_until"] == 1000.0 + 2 * 3600
    assert state.get_mode("c1", now=1000.0 + 3600)["mode"] == "bypass"
    expired = state.get_mode("c1", now=1000.0 + 2 * 3600)
    assert expired["mode"] == "manual" and expired["expired"] is True
    assert state.get_mode("c1", now=1000.0 + 2 * 3600 + 1)["expired"] is False


def test_bypass_without_time_limit(state, monkeypatch):
    monkeypatch.setattr(mode_state, "bypass_hours", lambda: 0.0)
    s = state.set_mode("c1", "bypass", now=1000.0)
    assert s["bypass_until"] == 0
    assert state.get_mode("c1", now=10**9)["mode"] == "bypass"


def test_default_can_never_be_bypass(monkeypatch):
    import helpers.settings as settings

    monkeypatch.setattr(settings, "get_settings", lambda: {"permissions_default_mode": "bypass"})
    assert _REAL_DEFAULT_MODE() == "manual"
    monkeypatch.setattr(settings, "get_settings", lambda: {})
    assert _REAL_DEFAULT_MODE() == "manual"  # shipped default is the safe one


def test_config_mode_key_is_ignored(state, monkeypatch):
    """A `mode: bypass` left in config.json must not switch anything on."""
    from helpers import plugins
    from plugins._permissions.helpers import config as perm_config

    monkeypatch.setattr(plugins, "get_plugin_config", lambda *a, **k: {"mode": "bypass"})

    class _Ctx:
        id = "c1"

    class _Agent:
        context = _Ctx()

    monkeypatch.setattr(mode_state, "context_project", lambda ctx: "")
    assert perm_config.get_config(_Agent())["mode"] == "manual"


# -- bypass_lock -------------------------------------------------------------

@pytest.fixture
def lockfile(monkeypatch, tmp_path):
    monkeypatch.setattr(bypass_lock.files, "get_abs_path", lambda *p: str(tmp_path / "bypass.json"))
    monkeypatch.setattr(bypass_lock, "ITERATIONS", 1000)  # fast tests
    import helpers.dotenv as dotenv

    monkeypatch.setattr(dotenv, "get_dotenv_value", lambda key: "login-password")
    return tmp_path / "bypass.json"


def test_password_set_verify_and_change(lockfile):
    assert bypass_lock.is_set() is False
    assert bypass_lock.verify("anything") is False
    bypass_lock.set_password("first-password")
    assert bypass_lock.is_set() and bypass_lock.verify("first-password")
    assert not bypass_lock.verify("wrong-password")
    assert "first-password" not in lockfile.read_text()  # only a hash on disk

    with pytest.raises(bypass_lock.BypassPasswordError):
        bypass_lock.set_password("second-password")  # current password missing
    with pytest.raises(bypass_lock.BypassPasswordError):
        bypass_lock.set_password("second-password", "wrong-password")
    bypass_lock.set_password("second-password", "first-password")
    assert bypass_lock.verify("second-password") and not bypass_lock.verify("first-password")


def test_password_rules(lockfile):
    with pytest.raises(bypass_lock.BypassPasswordError):
        bypass_lock.set_password("short")
    with pytest.raises(bypass_lock.BypassPasswordError, match="different"):
        bypass_lock.set_password("login-password")


# -- agent can't touch the lock ------------------------------------------------

@pytest.mark.parametrize(
    "args",
    [
        {"runtime": "terminal", "code": "Get-Content C:\\a0\\usr\\permissions_bypass.json"},
        {"action": "write", "path": "C:/a0/usr/permissions_bypass.json", "content": "{}"},
        {"runtime": "python", "code": "requests.post('http://localhost:5000/api/permissions_mode', json={'mode':'bypass'})"},
        {"runtime": "terminal", "code": "Remove-Item C:\\a0\\usr\\security_audit.jsonl"},
    ],
)
def test_protected_targets_are_detected(args):
    from plugins._permissions.extensions.python.tool_execute_before._06_permissions import (
        _references_protected_target,
    )

    assert _references_protected_target(args)


def test_ordinary_calls_are_not_flagged():
    from plugins._permissions.extensions.python.tool_execute_before._06_permissions import (
        _references_protected_target,
    )

    assert _references_protected_target({"runtime": "terminal", "code": "git status"}) == ""


# -- allowlist endpoint lockout guard --------------------------------------------

class _Req:
    def __init__(self, ip, remote=True):
        self.remote_addr = "127.0.0.1"
        self.headers = {"cf-connecting-ip": ip, "cf-ray": "x"} if remote else {}


@pytest.fixture
def sec(monkeypatch):
    from api import security_settings as sec_api

    store = {"tunnel_ip_allowlist": "203.0.113.114", "tunnel_allowlist_enabled": True}
    monkeypatch.setattr(sec_api.settings_helper, "get_settings", lambda: dict(store))
    monkeypatch.setattr(sec_api.settings_helper, "set_settings_delta", lambda d: store.update(d))
    monkeypatch.setattr(sec_api.access_control, "_active_tunnel_provider", lambda: "cloudflared")
    monkeypatch.setattr(sec_api.access_control, "audit", lambda *a, **k: None)
    monkeypatch.setattr(sec_api.bypass_lock, "verify", lambda pw: pw == "bypass-pw")
    monkeypatch.setattr(sec_api.bypass_lock, "is_set", lambda: True)
    return sec_api, store


@pytest.mark.asyncio
async def test_remote_change_that_locks_yourself_out_needs_bypass_password(sec):
    sec_api, store = sec
    handler = sec_api.SecuritySettings(app=None, thread_lock=None)  # type: ignore[arg-type]
    req = _Req("203.0.113.114")

    r = await handler.process({"action": "save_allowlist", "text": "1.2.3.4", "enabled": True}, req)
    assert r["ok"] is False and r["needs_password"]
    assert store["tunnel_ip_allowlist"] == "203.0.113.114"

    r = await handler.process({"action": "save_allowlist", "text": "1.2.3.4", "enabled": True, "password": "bypass-pw"}, req)
    assert r["ok"] is True and store["tunnel_ip_allowlist"] == "1.2.3.4"


@pytest.mark.asyncio
async def test_local_change_needs_no_password_and_invalid_entries_rejected(sec):
    sec_api, store = sec
    handler = sec_api.SecuritySettings(app=None, thread_lock=None)  # type: ignore[arg-type]
    local = _Req("", remote=False)

    r = await handler.process({"action": "save_allowlist", "text": "not-an-ip", "enabled": True}, local)
    assert r["ok"] is False

    r = await handler.process({"action": "save_allowlist", "text": "10.0.0.0/8", "enabled": True}, local)
    assert r["ok"] is True and store["tunnel_ip_allowlist"] == "10.0.0.0/8"

    r = await handler.process({"action": "allow_ip", "ip": "203.0.113.9"}, local)
    assert r["ok"] is True and "203.0.113.9" in store["tunnel_ip_allowlist"]

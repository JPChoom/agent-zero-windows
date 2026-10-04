"""helpers/access_control.py: local vs tunneled requests, real client IP,
the tunnel IP allowlist, the ASGI middleware, and the login throttle."""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from helpers import access_control as ac

ALLOWED = "203.0.113.114"
CF = {"cf-connecting-ip": ALLOWED, "cf-ray": "abc"}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(ac, "AUDIT_FILE", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(ac.files, "get_abs_path", lambda *p: str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(ac, "_maybe_notify_block_burst", lambda: None)
    ac._recent_blocks.clear()
    ac.invalidate_policy_cache()


def _policy(monkeypatch, text=ALLOWED + "  # offsite", enabled=True):
    monkeypatch.setattr(ac, "_current_policy", lambda: (enabled, ac.parse_allowlist(text)))


# -- local vs proxied ------------------------------------------------------

def test_plain_loopback_is_local():
    assert ac.is_local_request("127.0.0.1", {}) is True
    assert ac.is_local_request("::1", {"host": "localhost"}) is True


@pytest.mark.parametrize("header", ["CF-Connecting-IP", "X-Forwarded-For", "Forwarded", "X-Real-IP", "CF-Ray"])
def test_loopback_with_proxy_header_is_not_local(header):
    assert ac.is_local_request("127.0.0.1", {header: "1.2.3.4"}) is False


def test_non_loopback_is_not_local():
    assert ac.is_local_request("192.168.1.20", {}) is False


# -- client ip -------------------------------------------------------------

def test_cf_connecting_ip_trusted_only_for_cloudflared():
    h = {"CF-Connecting-IP": ALLOWED, "X-Forwarded-For": "6.6.6.6"}
    assert ac.client_ip("127.0.0.1", h, provider="cloudflared") == ALLOWED
    # Through another proxy a client could forge CF-Connecting-IP.
    assert ac.client_ip("127.0.0.1", h, provider="serveo") == "6.6.6.6"


def test_xff_uses_rightmost_entry():
    h = {"X-Forwarded-For": "1.1.1.1, 9.9.9.9"}  # left part is client-controlled
    assert ac.client_ip("127.0.0.1", h, provider=None) == "9.9.9.9"


def test_proxied_without_usable_address_is_unknown():
    assert ac.client_ip("127.0.0.1", {"CF-Ray": "x"}, provider=None) == ""


# -- allowlist -------------------------------------------------------------

def test_allowlist_parsing_and_matching():
    nets = ac.parse_allowlist(f"{ALLOWED}  # offsite\n10.0.0.0/8\n2001:db8::/32\nnot-an-ip")
    assert ac.ip_in_allowlist(ALLOWED, nets)
    assert ac.ip_in_allowlist("10.20.30.40", nets)
    assert ac.ip_in_allowlist("2001:db8::5", nets)
    assert ac.ip_in_allowlist("::ffff:" + ALLOWED, nets)  # IPv4-mapped
    assert not ac.ip_in_allowlist("203.0.113.115", nets)
    assert not ac.ip_in_allowlist("", nets)
    assert ac.invalid_allowlist_entries("1.2.3.4\nnot-an-ip\n# c") == ["not-an-ip"]


def test_check_access_tunnel_allowed_and_blocked(monkeypatch):
    _policy(monkeypatch)
    monkeypatch.setattr(ac, "_active_tunnel_provider", lambda: "cloudflared")
    assert ac.check_access("127.0.0.1", CF)[0] is True
    assert ac.check_access("127.0.0.1", {"cf-connecting-ip": "8.8.8.8"})[0] is False
    assert ac.check_access("127.0.0.1", {})[0] is True  # this PC


def test_spoofed_xff_cannot_impersonate_allowed_ip(monkeypatch):
    _policy(monkeypatch)
    monkeypatch.setattr(ac, "_active_tunnel_provider", lambda: "cloudflared")
    h = {"cf-connecting-ip": "8.8.8.8", "x-forwarded-for": ALLOWED}
    assert ac.check_access("127.0.0.1", h)[0] is False


def test_empty_allowlist_blocks_all_remote(monkeypatch):
    _policy(monkeypatch, text="")
    monkeypatch.setattr(ac, "_active_tunnel_provider", lambda: "cloudflared")
    assert ac.check_access("127.0.0.1", CF)[0] is False


def test_disabled_allowlist_allows_remote(monkeypatch):
    _policy(monkeypatch, text="", enabled=False)
    assert ac.check_access("127.0.0.1", CF)[0] is True


# -- middleware -------------------------------------------------------------

class _App:
    def __init__(self):
        self.called = False

    async def __call__(self, scope, receive, send):
        self.called = True


async def _run(mw, scope, messages=None):
    sent = []
    inbox = list(messages or [])

    async def receive():
        return inbox.pop(0) if inbox else {"type": "http.disconnect"}

    async def send(msg):
        sent.append(msg)

    await mw(scope, receive, send)
    return sent


def _scope(kind, headers, path="/"):
    return {
        "type": kind,
        "client": ("127.0.0.1", 50000),
        "path": path,
        "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
    }


@pytest.mark.asyncio
async def test_middleware_blocks_with_bare_404(monkeypatch):
    _policy(monkeypatch)
    monkeypatch.setattr(ac, "_active_tunnel_provider", lambda: "cloudflared")
    app = _App()
    sent = await _run(ac.AccessControlMiddleware(app), _scope("http", {"cf-connecting-ip": "8.8.8.8"}, "/js/api.js"))
    assert app.called is False
    assert sent[0]["status"] == 404
    assert sent[1]["body"] == b"Not Found"
    assert ac.recent_blocks()[0]["ip"] == "8.8.8.8"


@pytest.mark.asyncio
async def test_middleware_rejects_blocked_websocket(monkeypatch):
    _policy(monkeypatch)
    monkeypatch.setattr(ac, "_active_tunnel_provider", lambda: "cloudflared")
    app = _App()
    sent = await _run(
        ac.AccessControlMiddleware(app),
        _scope("websocket", {"cf-connecting-ip": "8.8.8.8"}),
        [{"type": "websocket.connect"}],
    )
    assert app.called is False
    assert sent == [{"type": "websocket.close", "code": 1008}]


@pytest.mark.asyncio
async def test_middleware_passes_allowed_and_local_and_lifespan(monkeypatch):
    _policy(monkeypatch)
    monkeypatch.setattr(ac, "_active_tunnel_provider", lambda: "cloudflared")
    for scope in (_scope("http", CF), _scope("http", {}), {"type": "lifespan"}):
        app = _App()
        await _run(ac.AccessControlMiddleware(app), scope)
        assert app.called is True


# -- login throttle ---------------------------------------------------------

def test_login_throttle_locks_after_max_failures_and_expires():
    t = ac.LoginThrottle()
    for i in range(t.MAX_FAILURES - 1):
        assert t.record_failure("ip", now=100 + i) is False
    assert t.is_locked("ip", now=110) is False
    assert t.record_failure("ip", now=111) is True
    assert t.is_locked("ip", now=112) is True
    assert t.is_locked("other", now=112) is False
    assert t.is_locked("ip", now=111 + t.LOCKOUT + 1) is False


def test_login_throttle_success_clears():
    t = ac.LoginThrottle()
    t.record_failure("ip", now=1)
    t.record_success("ip")
    assert t._failures.get("ip") is None


def test_constant_time_equals():
    assert ac.constant_time_equals("a", "a")
    assert not ac.constant_time_equals("a", "b")
    assert not ac.constant_time_equals(None, "a")

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


# -- forensic audit log -------------------------------------------------------

def _records(tmp_path):
    import json
    p = tmp_path / "audit.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


@pytest.fixture
def _fresh_history(monkeypatch):
    monkeypatch.setattr(ac, "_ip_history", None)
    ac._last_remote_visit.clear()


def test_describe_request_records_details_but_never_secrets(monkeypatch, _fresh_history):
    _policy(monkeypatch)
    monkeypatch.setattr(ac, "_active_tunnel_provider", lambda: "cloudflared")
    d = ac.describe_request(
        "127.0.0.1",
        {**CF, "cf-ipcountry": "CA", "user-agent": "Mozilla/5.0 Firefox/131.0", "cookie": "session=SECRET",
         "x-csrf-token": "TOKEN", "accept-language": "en-CA"},
        method="POST", path="/login", query="next=/&token=abc123", scheme="https", http_version="HTTP/1.1",
        remote_port=50123,
    )
    assert d["ip"] == ALLOWED and d["via"] == "tunnel:cloudflared" and d["allowlisted"] is True
    assert d["country"] == "CA" and d["cf_ray"] == "abc" and d["remote_port"] == 50123
    assert d["user_agent"].startswith("Mozilla") and d["accept_language"] == "en-CA"
    assert d["headers"]["cookie"] == d["headers"]["x-csrf-token"] == "[present, not stored]"
    assert "abc123" not in d["query"] and "next=%2F" in d["query"]
    blob = str(d)
    assert "SECRET" not in blob and "TOKEN" not in blob


def test_local_request_is_described_as_local(monkeypatch, _fresh_history):
    _policy(monkeypatch)
    d = ac.describe_request("127.0.0.1", {"host": "localhost:5000"})
    assert d["via"] == "local" and d["allowlisted"] is False and d["ip"] == "127.0.0.1"


def test_audit_tracks_whether_an_ip_was_seen_before(tmp_path, _fresh_history):
    ac.audit("login_failure", ip="198.51.100.7")
    ac.audit("login_success", ip="198.51.100.7")
    first, second = _records(tmp_path)
    assert first["ip_seen_before"] is False and first["ip_prior_events"] == 0
    assert second["ip_seen_before"] is True and second["ip_prior_events"] == 1
    assert second["ip_first_seen"] == first["time"]
    assert "local_time" in first


def test_ip_history_survives_a_restart(tmp_path, monkeypatch, _fresh_history):
    ac.audit("blocked", ip="198.51.100.9")
    monkeypatch.setattr(ac, "_ip_history", None)  # as after a restart
    ac.audit("blocked", ip="198.51.100.9")
    assert _records(tmp_path)[-1]["ip_seen_before"] is True


def test_remote_visit_logged_once_per_quiet_period(tmp_path, monkeypatch, _fresh_history):
    clock = [1000.0]
    monkeypatch.setattr(ac.time, "monotonic", lambda: clock[0])
    for _ in range(3):
        ac.note_remote_visit({"ip": ALLOWED, "path": "/"})
    clock[0] += ac.REMOTE_VISIT_GAP_SECONDS + 1
    ac.note_remote_visit({"ip": ALLOWED, "path": "/"})
    assert [r["event"] for r in _records(tmp_path)] == ["remote_access", "remote_access"]


@pytest.mark.asyncio
async def test_middleware_logs_allowed_remote_and_blocked_with_details(tmp_path, monkeypatch, _fresh_history):
    _policy(monkeypatch)
    monkeypatch.setattr(ac, "_active_tunnel_provider", lambda: "cloudflared")
    await _run(ac.AccessControlMiddleware(_App()), _scope("http", {**CF, "user-agent": "UA-ok"}, "/"))
    await _run(ac.AccessControlMiddleware(_App()), _scope("http", {"cf-connecting-ip": "8.8.8.8", "user-agent": "UA-bad"}, "/x"))
    await _run(ac.AccessControlMiddleware(_App()), _scope("http", {}, "/"))  # this PC: not logged
    visit, block = _records(tmp_path)
    assert visit["event"] == "remote_access" and visit["ip"] == ALLOWED and visit["user_agent"] == "UA-ok"
    assert block["event"] == "blocked" and block["ip"] == "8.8.8.8" and block["allowlisted"] is False
    assert block["user_agent"] == "UA-bad" and block["reason"] == "not on allowlist"


def test_rotation_keeps_records_instead_of_truncating(tmp_path, monkeypatch, _fresh_history):
    monkeypatch.setattr(ac, "AUDIT_MAX_BYTES", 200)
    monkeypatch.setattr(ac, "AUDIT_KEEP_FILES", 2)
    for i in range(12):
        ac.audit("blocked", ip=f"198.51.100.{i}", pad="x" * 60)
    archives = sorted(p.name for p in tmp_path.iterdir())
    assert archives == ["audit.1.jsonl", "audit.2.jsonl", "audit.jsonl"]


def test_read_audit_log_is_newest_first_and_filters(tmp_path, _fresh_history):
    for event in ("login_failure", "blocked", "login_success", "remote_access"):
        ac.audit(event, ip="198.51.100.20")
    assert [r["event"] for r in ac.read_audit_log(10)] == ["remote_access", "login_success", "blocked", "login_failure"]
    assert [r["event"] for r in ac.read_audit_log(10, ["login_success", "login_failure"])] == ["login_success", "login_failure"]
    assert len(ac.read_audit_log(1)) == 1


def test_remote_sign_in_from_new_address_notifies_high(monkeypatch, _fresh_history):
    sent = []
    from helpers import notification
    monkeypatch.setattr(notification.NotificationManager, "send_notification", staticmethod(lambda **kw: sent.append(kw)))
    details = {"ip": "198.51.100.30", "via": "tunnel:cloudflared", "country": "CA"}
    ac.record_login("login_success", details, username="u")
    ac.record_login("login_success", details, username="u")
    ac.record_login("login_success", {"ip": "127.0.0.1", "via": "local"}, username="u")
    assert [s["priority"] for s in sent] == [notification.NotificationPriority.HIGH, notification.NotificationPriority.NORMAL]


def test_failure_count_tracks_the_window():
    t = ac.LoginThrottle()
    t.record_failure("ip", now=100)
    t.record_failure("ip", now=101)
    assert t.failure_count("ip", now=102) == 2
    assert t.failure_count("ip", now=100 + t.WINDOW + 5) == 0

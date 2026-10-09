"""Network access control: who is local, who came through a tunnel or proxy,
and whether a remote client's IP is on the allowlist.

Why this exists: a tunnel client (cloudflared, serveo's ssh, ...) runs on
this machine and connects to the web UI from localhost, so every tunnel
request arrives with a loopback `remote_addr`. Trusting `remote_addr` alone
made "loopback-only" endpoints reachable from the internet through the
tunnel. Proxies add forwarding headers; a request from loopback that carries
any of them is treated as remote.

Client IP for a proxied request:
- Cloudflare tunnel: `CF-Connecting-IP`, set by Cloudflare's edge (which
  overwrites any client-supplied value). Trusted only while the running
  tunnel provider is cloudflared - through any other proxy a client could
  send that header itself.
- Any other proxy: the right-most `X-Forwarded-For` entry, i.e. the one the
  nearest proxy appended (left-most entries are client-controlled).

Policy (enforced by AccessControlMiddleware around the whole ASGI app, so it
covers Flask routes, static files, Socket.IO/WebSocket, /mcp and /a2a):
- Local (loopback, no forwarding headers): always allowed.
- Anything else: allowed only if its client IP matches
  `tunnel_ip_allowlist` (IPs/CIDRs, one per line). Empty list = nobody
  (fail closed). Blocked requests get a bare 404, the same as a path that
  doesn't exist, so the site doesn't reveal that anything is there.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import os
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Iterable, Mapping
from urllib.parse import parse_qsl, urlencode

from helpers import files
from helpers.network import is_loopback_address

PROXY_HEADERS = (
    "cf-connecting-ip",
    "cf-ray",
    "cf-ipcountry",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-real-ip",
    "forwarded",
)

AUDIT_FILE = "usr/security_audit.jsonl"
AUDIT_MAX_BYTES = 10 * 1024 * 1024
AUDIT_KEEP_FILES = 20
REMOTE_VISIT_GAP_SECONDS = 30 * 60
_SETTINGS_TTL_SECONDS = 2.0

# Recorded as present, never stored: they carry the session, CSRF token or credentials.
SENSITIVE_HEADERS = frozenset({
    "cookie", "set-cookie", "authorization", "proxy-authorization",
    "x-csrf-token", "x-api-key", "x-auth-token",
})
_SENSITIVE_QUERY_KEY = re.compile(r"token|key|secret|pass|auth|session|sig|code", re.IGNORECASE)
_MAX_HEADER_VALUE = 500

_lock = threading.Lock()
_settings_cache: tuple[float, str, bool] | None = None
_parsed_cache: tuple[str, list] | None = None
_recent_blocks: deque = deque(maxlen=50)
_ip_history: dict[str, dict] | None = None
_last_remote_visit: dict[str, float] = {}


# ----------------------------------------------------------------- headers

def _lower_headers(headers: Mapping[str, str] | Iterable[tuple]) -> dict[str, str]:
    if isinstance(headers, Mapping):
        items = headers.items()
    else:
        items = headers
    out: dict[str, str] = {}
    for key, value in items:
        if isinstance(key, bytes):
            key = key.decode("latin-1")
        if isinstance(value, bytes):
            value = value.decode("latin-1")
        out[str(key).lower()] = str(value)
    return out


def is_proxied(headers: Mapping[str, str]) -> bool:
    h = _lower_headers(headers)
    return any(name in h for name in PROXY_HEADERS)


def is_local_request(remote_addr: str | None, headers: Mapping[str, str]) -> bool:
    """True only for a request made on this machine without any proxy in
    between. A tunnel client on localhost does not count."""
    if not remote_addr or not is_loopback_address(str(remote_addr)):
        return False
    return not is_proxied(headers)


def _active_tunnel_provider() -> str | None:
    try:
        from helpers.tunnel_manager import TunnelManager

        manager = TunnelManager.get_instance()
        return manager.provider if manager.is_running else None
    except Exception:
        return None


def client_ip(remote_addr: str | None, headers: Mapping[str, str], provider: str | None = "__auto__") -> str:
    """Best determination of the real client IP."""
    h = _lower_headers(headers)
    if remote_addr and is_loopback_address(str(remote_addr)) and is_proxied(h):
        if provider == "__auto__":
            provider = _active_tunnel_provider()
        cf_ip = h.get("cf-connecting-ip", "").strip()
        if cf_ip and provider == "cloudflared":
            return cf_ip
        xff = h.get("x-forwarded-for", "")
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
        real_ip = h.get("x-real-ip", "").strip()
        if real_ip:
            return real_ip
        # Proxied, but no usable client address: unknown, never "local".
        return ""
    return str(remote_addr or "")


# --------------------------------------------------------------- allowlist

def parse_allowlist(text: str) -> list:
    networks = []
    for raw in str(text or "").replace(",", "\n").splitlines():
        entry = raw.split("#", 1)[0].strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            continue  # invalid entries are ignored (validated in the UI on save)
    return networks


def invalid_allowlist_entries(text: str) -> list[str]:
    bad = []
    for raw in str(text or "").replace(",", "\n").splitlines():
        entry = raw.split("#", 1)[0].strip()
        if not entry:
            continue
        try:
            ipaddress.ip_network(entry, strict=False)
        except ValueError:
            bad.append(entry)
    return bad


def ip_in_allowlist(ip: str, networks: list) -> bool:
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return False
    if getattr(addr, "ipv4_mapped", None):
        addr = addr.ipv4_mapped  # ::ffff:1.2.3.4 -> 1.2.3.4
    return any(addr.version == net.version and addr in net for net in networks)


def _current_policy() -> tuple[bool, list]:
    """(enabled, networks), cached briefly - this runs on every request and
    settings.get_settings() reads files."""
    global _settings_cache, _parsed_cache
    now = time.monotonic()
    with _lock:
        cached = _settings_cache
    if cached is None or now - cached[0] > _SETTINGS_TTL_SECONDS:
        try:
            from helpers.settings import get_settings

            s = get_settings()
            text = str(s.get("tunnel_ip_allowlist", "") or "")
            enabled = bool(s.get("tunnel_allowlist_enabled", True))
        except Exception:
            # Settings unreadable: keep the last known policy, or fail closed.
            text, enabled = (cached[1], cached[2]) if cached else ("", True)
        with _lock:
            _settings_cache = (now, text, enabled)
        cached = (now, text, enabled)
    _, text, enabled = cached
    with _lock:
        if _parsed_cache is None or _parsed_cache[0] != text:
            _parsed_cache = (text, parse_allowlist(text))
        networks = _parsed_cache[1]
    return enabled, networks


def invalidate_policy_cache() -> None:
    global _settings_cache
    with _lock:
        _settings_cache = None


def check_access(remote_addr: str | None, headers) -> tuple[bool, str, str]:
    """(allowed, client_ip, reason)."""
    h = _lower_headers(headers)
    if is_local_request(remote_addr, h):
        return True, str(remote_addr or ""), "local"
    enabled, networks = _current_policy()
    ip = client_ip(remote_addr, h)
    if not enabled:
        return True, ip, "allowlist disabled"
    if ip_in_allowlist(ip, networks):
        return True, ip, "allowlisted"
    return False, ip, "not on allowlist" if ip else "unknown client address"


# ----------------------------------------------------------- request details

def _redact_query(query: str) -> str:
    if not query:
        return ""
    pairs = parse_qsl(query, keep_blank_values=True)
    if not pairs:
        return query[:300]
    cleaned = [(k, "[redacted]" if _SENSITIVE_QUERY_KEY.search(k) else v) for k, v in pairs]
    return urlencode(cleaned)[:300]


def describe_request(
    remote_addr: str | None,
    headers,
    *,
    method: str = "",
    path: str = "",
    query: str = "",
    scheme: str = "",
    http_version: str = "",
    kind: str = "http",
    remote_port=None,
) -> dict:
    """Everything this server can learn about one request, for the security
    audit log. Credentials, cookies and CSRF tokens are noted as present but
    never stored."""
    h = _lower_headers(headers)
    local = is_local_request(remote_addr, h)
    provider = None if local else _active_tunnel_provider()
    ip = str(remote_addr or "") if local else client_ip(remote_addr, h, provider=provider)
    enabled, networks = _current_policy()
    if local:
        via = "local"
    elif provider:
        via = f"tunnel:{provider}"
    elif is_proxied(h):
        via = "proxy"
    else:
        via = "direct"
    recorded_headers = {
        name: ("[present, not stored]" if name in SENSITIVE_HEADERS else value[:_MAX_HEADER_VALUE])
        for name, value in sorted(h.items())
    }
    return {
        "ip": ip or "?",
        "via": via,
        "remote_addr": str(remote_addr or ""),
        "remote_port": remote_port,
        "allowlisted": (not local) and ip_in_allowlist(ip, networks),
        "allowlist_enabled": enabled,
        "country": h.get("cf-ipcountry", ""),
        "cf_ray": h.get("cf-ray", ""),
        "user_agent": h.get("user-agent", "")[:_MAX_HEADER_VALUE],
        "accept_language": h.get("accept-language", "")[:200],
        "referer": h.get("referer", "")[:_MAX_HEADER_VALUE],
        "origin": h.get("origin", "")[:200],
        "host": h.get("host", "")[:200],
        "kind": kind,
        "method": method,
        "path": str(path or "")[:300],
        "query": _redact_query(str(query or "")),
        "scheme": scheme or h.get("x-forwarded-proto", ""),
        "http_version": str(http_version or ""),
        "forwarded_for": h.get("x-forwarded-for", "")[:300],
        "headers": recorded_headers,
    }


def describe_scope(scope) -> dict:
    client = scope.get("client") or (None, None)
    raw_query = scope.get("query_string") or b""
    return describe_request(
        client[0],
        scope.get("headers") or [],
        method=str(scope.get("method") or ("WS" if scope.get("type") == "websocket" else "")),
        path=str(scope.get("path", "")),
        query=raw_query.decode("latin-1") if isinstance(raw_query, bytes) else str(raw_query),
        scheme=str(scope.get("scheme") or ""),
        http_version=str(scope.get("http_version") or ""),
        kind=str(scope.get("type") or ""),
        remote_port=client[1] if len(client) > 1 else None,
    )


# ------------------------------------------------------------------- audit

def _audit_path() -> str:
    return files.get_abs_path(AUDIT_FILE)


def _rotate_if_needed(path: str) -> None:
    """Keeps every record: the full file is renamed, never truncated, and only
    the oldest of AUDIT_KEEP_FILES archives is removed. Caller holds _lock."""
    try:
        if os.path.getsize(path) < AUDIT_MAX_BYTES:
            return
    except OSError:
        return
    base, ext = os.path.splitext(path)
    oldest = f"{base}.{AUDIT_KEEP_FILES}{ext}"
    if os.path.exists(oldest):
        os.remove(oldest)
    for n in range(AUDIT_KEEP_FILES - 1, 0, -1):
        src = f"{base}.{n}{ext}"
        if os.path.exists(src):
            os.replace(src, f"{base}.{n + 1}{ext}")
    os.replace(path, f"{base}.1{ext}")


def _load_ip_history() -> dict[str, dict]:
    """ip -> {first_seen, events}, seeded once from the current audit file so
    "seen before" survives a restart. Caller holds _lock."""
    global _ip_history
    if _ip_history is not None:
        return _ip_history
    history: dict[str, dict] = {}
    try:
        with open(_audit_path(), "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                ip = rec.get("ip")
                if not ip or ip == "?":
                    continue
                entry = history.setdefault(ip, {"first_seen": rec.get("time", ""), "events": 0})
                entry["events"] += 1
    except OSError:
        pass
    _ip_history = history
    return history


def audit(event: str, **fields) -> None:
    now = datetime.now(timezone.utc)
    record = {
        "time": now.isoformat(),
        "local_time": now.astimezone().isoformat(),
        "event": event,
        **fields,
    }
    try:
        path = _audit_path()
        with _lock:
            ip = record.get("ip")
            if ip and ip != "?":
                history = _load_ip_history()
                prior = history.get(ip)
                record.setdefault("ip_seen_before", prior is not None)
                record.setdefault("ip_first_seen", prior["first_seen"] if prior else record["time"])
                record.setdefault("ip_prior_events", prior["events"] if prior else 0)
                entry = history.setdefault(ip, {"first_seen": record["time"], "events": 0})
                entry["events"] += 1
            _rotate_if_needed(path)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
    except Exception:
        pass


def read_audit_log(limit: int = 200, kinds: Iterable[str] | None = None) -> list[dict]:
    """Newest-first records from the current audit file, optionally only the
    given event names."""
    wanted = set(kinds) if kinds else None
    limit = max(1, min(int(limit or 200), 2000))
    try:
        with open(_audit_path(), "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if wanted is None or rec.get("event") in wanted:
            out.append(rec)
            if len(out) >= limit:
                break
    return out


def note_remote_visit(details: dict) -> None:
    """Log an allowed remote client once per REMOTE_VISIT_GAP_SECONDS of
    activity, so normal use doesn't log every request."""
    ip = details.get("ip") or "?"
    now = time.monotonic()
    with _lock:
        last = _last_remote_visit.get(ip)
        _last_remote_visit[ip] = now
    if last is not None and now - last < REMOTE_VISIT_GAP_SECONDS:
        return
    audit("remote_access", **details)


def record_block(ip: str, path: str, reason: str, country: str = "", details: dict | None = None) -> None:
    entry = {
        "time": datetime.now(timezone.utc).isoformat(),
        "ip": ip or "?",
        "path": path[:200],
        "reason": reason,
        "country": country,
    }
    with _lock:
        _recent_blocks.appendleft(entry)
    audit("blocked", **{**(details or {}), **entry})
    _maybe_notify_block_burst()


_last_block_notice = 0.0


def _maybe_notify_block_burst() -> None:
    global _last_block_notice
    now = time.time()
    with _lock:
        recent = [b for b in list(_recent_blocks)[:20]]
        if now - _last_block_notice < 600 or len(recent) < 5:
            return
        _last_block_notice = now
    try:
        from helpers.notification import NotificationManager, NotificationPriority, NotificationType

        NotificationManager.send_notification(
            type=NotificationType.WARNING,
            priority=NotificationPriority.HIGH,
            title="Blocked remote access attempts",
            message="Requests from addresses not on the tunnel allowlist were blocked.",
            detail="See Settings > Security for the blocked addresses.",
            display_time=10,
            group="access_control",
            id="access_control_blocked_burst",
        )
    except Exception:
        pass


def flask_request_details(request) -> dict:
    environ = getattr(request, "environ", {}) or {}
    raw_query = getattr(request, "query_string", b"") or b""
    return describe_request(
        request.remote_addr,
        request.headers,
        method=request.method,
        path=request.path,
        query=raw_query.decode("latin-1") if isinstance(raw_query, bytes) else str(raw_query),
        scheme=request.scheme,
        http_version=environ.get("SERVER_PROTOCOL", ""),
        remote_port=environ.get("REMOTE_PORT"),
    )


def record_login(event: str, details: dict, **fields) -> None:
    """Audit a sign-in event; a successful remote sign-in also raises a
    notification, high priority when the address has never been seen."""
    with _lock:
        seen_before = details.get("ip") in _load_ip_history()
    audit(event, **details, **fields)
    if event != "login_success" or details.get("via") == "local":
        return
    try:
        from helpers.notification import NotificationManager, NotificationPriority, NotificationType

        place = f" ({details['country']})" if details.get("country") else ""
        NotificationManager.send_notification(
            type=NotificationType.INFO if seen_before else NotificationType.WARNING,
            priority=NotificationPriority.NORMAL if seen_before else NotificationPriority.HIGH,
            title="Remote sign-in" if seen_before else "Remote sign-in from a new address",
            message=f"Signed in from {details.get('ip', '?')}{place}.",
            detail="See Settings > Security > Access log for the full record.",
            display_time=10,
            group="access_control",
        )
    except Exception:
        pass


def recent_blocks() -> list[dict]:
    with _lock:
        return list(_recent_blocks)


# ------------------------------------------------------------ login guard

class LoginThrottle:
    """Per-client failed-login limiter: after MAX_FAILURES within WINDOW
    seconds the client is locked out for LOCKOUT seconds. Keyed by the real
    client IP (so all tunnel visitors aren't lumped together as 127.0.0.1)."""

    MAX_FAILURES = 5
    WINDOW = 15 * 60
    LOCKOUT = 15 * 60

    def __init__(self):
        self._failures: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}
        self._mutex = threading.Lock()

    def is_locked(self, key: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self._mutex:
            until = self._locked_until.get(key, 0)
            if until and now >= until:
                self._locked_until.pop(key, None)
                self._failures.pop(key, None)
                return False
            return until > now

    def record_failure(self, key: str, now: float | None = None) -> bool:
        """Returns True if this failure triggered a lockout."""
        now = time.time() if now is None else now
        with self._mutex:
            attempts = [t for t in self._failures.get(key, []) if now - t < self.WINDOW]
            attempts.append(now)
            self._failures[key] = attempts
            if len(attempts) >= self.MAX_FAILURES:
                self._locked_until[key] = now + self.LOCKOUT
                return True
            return False

    def failure_count(self, key: str, now: float | None = None) -> int:
        now = time.time() if now is None else now
        with self._mutex:
            return len([t for t in self._failures.get(key, []) if now - t < self.WINDOW])

    def record_success(self, key: str) -> None:
        with self._mutex:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)


login_throttle = LoginThrottle()


def constant_time_equals(a: str | None, b: str | None) -> bool:
    return hmac.compare_digest(str(a or "").encode("utf-8"), str(b or "").encode("utf-8"))


# ---------------------------------------------------------- ASGI middleware

_NOT_FOUND_BODY = b"Not Found"


class AccessControlMiddleware:
    """Outermost ASGI wrapper enforcing check_access() for every http and
    websocket connection. Lifespan events pass through untouched."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        kind = scope.get("type")
        if kind not in ("http", "websocket"):
            return await self.app(scope, receive, send)

        client = scope.get("client") or (None, None)
        headers = scope.get("headers") or []
        allowed, ip, reason = check_access(client[0], headers)
        if allowed:
            if reason != "local":
                try:
                    note_remote_visit({**describe_scope(scope), "reason": reason})
                except Exception:
                    pass
            return await self.app(scope, receive, send)

        h = _lower_headers(headers)
        try:
            details = describe_scope(scope)
        except Exception:
            details = None
        record_block(ip, str(scope.get("path", "")), reason, h.get("cf-ipcountry", ""), details=details)

        if kind == "websocket":
            # Reject the handshake before accepting it.
            message = await receive()
            if message.get("type") == "websocket.connect":
                await send({"type": "websocket.close", "code": 1008})
            return

        await send({
            "type": "http.response.start",
            "status": 404,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(_NOT_FOUND_BODY)).encode()),
                (b"cache-control", b"no-store"),
                (b"x-robots-tag", b"noindex, nofollow"),
            ],
        })
        await send({"type": "http.response.body", "body": _NOT_FOUND_BODY})

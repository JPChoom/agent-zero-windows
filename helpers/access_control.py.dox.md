# access_control.py DOX

## Purpose

- Own network access control: local vs tunneled/proxied requests, real client IP, the remote-access IP allowlist, the login throttle, and the outermost ASGI gate.

## Ownership

- `access_control.py` owns the runtime implementation; this file owns its contracts.
- Public API: `is_proxied`, `is_local_request`, `client_ip`, `parse_allowlist`, `invalid_allowlist_entries`, `ip_in_allowlist`, `check_access`, `invalidate_policy_cache`, `audit`, `record_block`, `recent_blocks`, `LoginThrottle` / `login_throttle`, `constant_time_equals`, `AccessControlMiddleware`.

## Runtime Contracts

- "Local" means loopback `remote_addr` **and** no proxy/forwarding header (`PROXY_HEADERS`). A tunnel client (cloudflared, serveo ssh, ...) connects from localhost, so loopback alone is never trusted. `helpers/api.py requires_loopback`, `helpers/ws.py`, `api/health.py`, and the `_oauth` proxy all use this definition.
- Client IP for proxied requests: `CF-Connecting-IP` only while the running tunnel provider is `cloudflared` (Cloudflare's edge overwrites it); otherwise the right-most `X-Forwarded-For` entry. Left-most XFF entries are client-controlled and never used. Proxied with no usable address -> `""` (blocked).
- `AccessControlMiddleware` wraps the whole ASGI app (`helpers/ui_server.py build_asgi_app`): every non-local http/websocket connection must match settings `tunnel_ip_allowlist` (IPs/CIDRs, `#` comments) while `tunnel_allowlist_enabled` is true. Empty list = no remote access (fail closed). Blocked http -> bare `404 Not Found`; blocked websocket -> close 1008 before accept. Lifespan passes through.
- Policy is read from settings with a 2s TTL cache; `helpers/settings.set_settings` calls `invalidate_policy_cache()`.
- Audit trail: append-only JSON lines in `usr/security_audit.jsonl` (blocks, login success/failure/lockout, bypass unlocks, allowlist changes). The permissions gate refuses agent tool calls that reference this file.
- `LoginThrottle`: 5 failures in 15 min -> 15 min lockout per client key; used by the login form and the Bypass unlock.

## Verification

- `pytest tests/test_access_control.py tests/test_http_auth_csrf.py tests/test_ws_security.py tests/test_csrf_tunnel_origins.py`
- Smoke: unauthenticated requests with/without `X-Forwarded-For`/`CF-Connecting-IP` headers against `/login`, `/js/api.js`, `/api/health`, `/api/scheduler_tick`.

## Child DOX Index

No child DOX files.

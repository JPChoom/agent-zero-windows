# access_control.py DOX

## Purpose

- Own network access control: local vs tunneled/proxied requests, real client IP, the remote-access IP allowlist, the login throttle, and the outermost ASGI gate.

## Ownership

- `access_control.py` owns the runtime implementation; this file owns its contracts.
- Public API: `is_proxied`, `is_local_request`, `client_ip`, `parse_allowlist`, `invalid_allowlist_entries`, `ip_in_allowlist`, `check_access`, `invalidate_policy_cache`, `describe_request`, `describe_scope`, `flask_request_details`, `audit`, `record_login`, `note_remote_visit`, `record_block`, `read_audit_log`, `recent_blocks`, `LoginThrottle` / `login_throttle`, `constant_time_equals`, `AccessControlMiddleware`.

## Runtime Contracts

- "Local" means loopback `remote_addr` **and** no proxy/forwarding header (`PROXY_HEADERS`). A tunnel client (cloudflared, serveo ssh, ...) connects from localhost, so loopback alone is never trusted. `helpers/api.py requires_loopback`, `helpers/ws.py`, `api/health.py`, and the `_oauth` proxy all use this definition.
- Client IP for proxied requests: `CF-Connecting-IP` only while the running tunnel provider is `cloudflared` (Cloudflare's edge overwrites it); otherwise the right-most `X-Forwarded-For` entry. Left-most XFF entries are client-controlled and never used. Proxied with no usable address -> `""` (blocked).
- `AccessControlMiddleware` wraps the whole ASGI app (`helpers/ui_server.py build_asgi_app`): every non-local http/websocket connection must match settings `tunnel_ip_allowlist` (IPs/CIDRs, `#` comments) while `tunnel_allowlist_enabled` is true. Empty list = no remote access (fail closed). Blocked http -> bare `404 Not Found`; blocked websocket -> close 1008 before accept. Lifespan passes through.
- Policy is read from settings with a 2s TTL cache; `helpers/settings.set_settings` calls `invalidate_policy_cache()`.
- Audit trail: append-only JSON lines in `usr/security_audit.jsonl`. Events: `blocked` (every refused request), `remote_access` (an allowed non-local client, once per IP per `REMOTE_VISIT_GAP_SECONDS` of activity), `login_success` / `login_failure` / `login_locked` / `logout` (any origin), plus bypass and allowlist changes from the API handlers. The permissions gate refuses agent tool calls that reference this file.
- Every record has UTC `time` and `local_time` (in the user's configured timezone via `Localization.get_tzinfo()`, else the OS zone); records with an `ip` also get `ip_seen_before`, `ip_first_seen`, `ip_prior_events` (history seeded once from the current file, so it survives a restart).
- `describe_request` captures the request forensics: client IP, `via` (local / `tunnel:<provider>` / proxy / direct), remote addr and port, allowlist match, country and CF-Ray, user agent, language, referer, origin, host, method, path, query, scheme, HTTP version, X-Forwarded-For and all headers. `SENSITIVE_HEADERS` (cookies, authorization, CSRF and API tokens) are recorded as present, never stored; query values whose key looks secret are replaced with `[redacted]`. Sign-ins add the attempted username (max 64 chars), never the password; a successful sign-in sets session `login_id`, repeated on `logout`.
- Rotation: at `AUDIT_MAX_BYTES` (10 MB) the file is renamed to `.1`, `.2`, ... and the oldest beyond `AUDIT_KEEP_FILES` (20) removed; records are never truncated. `read_audit_log` reads only the current file.
- `record_login` raises a notification for every successful non-local sign-in (warning + high priority when the address was never seen). TLS details are not available (Cloudflare terminates TLS) and no third-party IP lookups are made.
- `LoginThrottle`: 5 failures in 15 min -> 15 min lockout per client key; used by the login form and the Bypass unlock.

## Verification

- `pytest tests/test_access_control.py tests/test_login_audit.py tests/test_http_auth_csrf.py tests/test_ws_security.py tests/test_csrf_tunnel_origins.py`
- Smoke: unauthenticated requests with/without `X-Forwarded-For`/`CF-Connecting-IP` headers against `/login`, `/js/api.js`, `/api/health`, `/api/scheduler_tick`.

## Child DOX Index

No child DOX files.

# security_settings.py DOX

## Purpose

- Own the `security_settings.py` API endpoint: the remote-access IP allowlist, its blocked-attempt list, and the access log viewer (Settings > Security).
- Keep this file-level DOX profile synchronized with `security_settings.py` because this directory is intentionally flat.

## Ownership

- `security_settings.py` owns the runtime implementation.
- Classes: `SecuritySettings` (`ApiHandler`).

## Runtime Contracts

- `action: "get"` -> `{ok, allowlist, enabled, invalid, blocked, is_local, my_ip, bypass_password_set}`.
- `action: "save_allowlist"` `{text, enabled, password?}` and `action: "allow_ip"` `{ip}` write settings `tunnel_ip_allowlist` / `tunnel_allowlist_enabled` via `helpers.settings.set_settings_delta` and invalidate the access-control cache. Invalid entries are rejected.
- `action: "audit_log"` `{filter?, limit?}` -> `{ok, records}`, newest first from `usr/security_audit.jsonl` (`access_control.read_audit_log`, limit max 2000). `filter` is a key of `AUDIT_FILTERS` (`all`, `logins`, `failed`, `remote`, `blocked`, `settings`).
- `action: "save_file_access"` `{config, password?}` saves the File Browser access settings (`helpers/file_access.py`). From a remote session, a change that widens local or remote access (`file_access.widens`) needs the Bypass password; narrowing never does. `get` returns them as `file_access`. Audited as `file_access_saved`. `audit_log` filter `files` returns every `file_*` event.
- Bypass-password confirmations go through `bypass_lock.check` (shared limiter with the Bypass unlock); wrong attempts are audited as `bypass_failure` with `purpose: security_settings`.
- Lockout guard: a change made remotely (not `access_control.is_local_request`) that would stop the requester's own client IP from getting in requires the Bypass password (`needs_password: true` otherwise).
- Default auth + CSRF apply. Every change is audited to `usr/security_audit.jsonl`.
- The frontend (`webui/components/settings/external/security-store.js`) mirrors saved values into `$store.settings` so the main Settings Save does not write back a stale allowlist.

## Verification

- `pytest tests/test_permissions_bypass_lock.py tests/test_access_control.py tests/test_login_audit.py`

## Child DOX Index

No child DOX files.

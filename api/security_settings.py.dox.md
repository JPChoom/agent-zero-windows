# security_settings.py DOX

## Purpose

- Own the `security_settings.py` API endpoint: the remote-access IP allowlist and its blocked-attempt log (Settings > Security).
- Keep this file-level DOX profile synchronized with `security_settings.py` because this directory is intentionally flat.

## Ownership

- `security_settings.py` owns the runtime implementation.
- Classes: `SecuritySettings` (`ApiHandler`).

## Runtime Contracts

- `action: "get"` -> `{ok, allowlist, enabled, invalid, blocked, is_local, my_ip, bypass_password_set}`.
- `action: "save_allowlist"` `{text, enabled, password?}` and `action: "allow_ip"` `{ip}` write settings `tunnel_ip_allowlist` / `tunnel_allowlist_enabled` via `helpers.settings.set_settings_delta` and invalidate the access-control cache. Invalid entries are rejected.
- Lockout guard: a change made remotely (not `access_control.is_local_request`) that would stop the requester's own client IP from getting in requires the Bypass password (`needs_password: true` otherwise).
- Default auth + CSRF apply. Every change is audited to `usr/security_audit.jsonl`.
- The frontend (`webui/components/settings/external/security-store.js`) mirrors saved values into `$store.settings` so the main Settings Save does not write back a stale allowlist.

## Verification

- `pytest tests/test_permissions_bypass_lock.py tests/test_access_control.py`

## Child DOX Index

No child DOX files.

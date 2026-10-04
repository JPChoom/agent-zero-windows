# permissions_bypass_password.py DOX

## Purpose

- Own the `permissions_bypass_password.py` API endpoint: status / set / change the Bypass-mode password (Settings > Security).
- Keep this file-level DOX profile synchronized with `permissions_bypass_password.py` because this directory is intentionally flat.

## Ownership

- `permissions_bypass_password.py` owns the runtime implementation.
- Classes: `PermissionsBypassPassword` (`ApiHandler`).

## Runtime Contracts

- `{}` -> `{ok, is_set}`.
- `{new_password, current_password?}` -> `{ok, is_set}` or `{ok:false, error, is_set}`. Changing an existing password requires the current one; min 8 chars; must differ from the web UI login password.
- Storage: salted PBKDF2-SHA256 hash only, in `usr/permissions_bypass.json` (`plugins/_permissions/helpers/bypass_lock.py`). Changes and failures are audited to `usr/security_audit.jsonl`.
- Default auth + CSRF apply. The permissions gate refuses agent tool calls that reference this endpoint or the hash file.

## Verification

- `pytest tests/test_permissions_bypass_lock.py`

## Child DOX Index

No child DOX files.

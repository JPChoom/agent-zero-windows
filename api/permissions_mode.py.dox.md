# permissions_mode.py DOX

## Purpose

- Own the `permissions_mode.py` API endpoint: read or set the permission mode of one chat (bottom-bar selector).
- Keep this file-level DOX profile synchronized with `permissions_mode.py` because this directory is intentionally flat.

## Ownership

- `permissions_mode.py` owns the runtime implementation.
- Classes: `PermissionsMode` (`ApiHandler`) - `async process(self, input: dict, request: Request) -> dict | Response`.
- Module state: `bypass_throttle` (`access_control.LoginThrottle`) for wrong Bypass passwords.

## Runtime Contracts

- Request: `ctxid` (chat id), optional `mode`, optional `password` (only for `mode: "bypass"`).
- Read (no `mode`): `{ok, mode, bypass_until, unlocked_at, default_mode, bypass_password_set, modes:[{id,label,description,color}]}` for that chat.
- Set: `{ok, mode, bypass_until, unlocked_at}` or `{ok:false, error, needs_setup|needs_password}`. Setting requires a `ctxid`.
- Modes are per chat and in memory (`plugins/_permissions/helpers/mode_state.py`); nothing is persisted, so restart / new chat / project switch returns to the `permissions_default_mode` setting.
- `bypass` requires a configured Bypass password (`plugins/_permissions/helpers/bypass_lock.py`) and the correct `password`; failures are rate-limited per client and audited to `usr/security_audit.jsonl`.
- Default auth + CSRF apply. The permissions gate refuses agent tool calls that reference this endpoint.

## Verification

- `pytest tests/test_permissions_api.py tests/test_permissions_bypass_lock.py`

## Child DOX Index

No child DOX files.

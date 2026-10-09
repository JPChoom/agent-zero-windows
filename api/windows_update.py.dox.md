# windows_update.py DOX

## Purpose

- Own the `windows_update` API endpoint behind Settings > Check for updates on native (non-Docker) installs.

## Ownership

- `windows_update.py` owns the runtime implementation. Classes: `WindowsUpdate` (`ApiHandler`).
- Update logic lives in `helpers/windows_update.py`; the frontend is `webui/components/settings/external/windows-update-store.js` rendered by `settings/backup/self-update.html`.

## Runtime Contracts

- `action: "check"` `{force?}` -> `{ok, ...windows_update.check()}`.
- `action: "apply"` `{tag}` / `action: "rollback"` run in a worker thread and return the helper result, or `{ok: false, error}` on `UpdateError`. Both are audited to `usr/security_audit.jsonl` (`update_apply`, `update_rollback`, `*_failed`) with the requester (`local` or client IP).
- `action: "restart"` audits `update_restart` and calls `helpers/process.reload` from a `threading.Timer` after 1 s. Not the request's event loop: that loop ends with the response, so a callback scheduled on it never runs.
- Default auth + CSRF apply.

## Verification

- `pytest tests/test_windows_update.py tests/test_tunnel_handover.py`

## Child DOX Index

No child DOX files.

# scheduler_settings_set.py DOX

## Purpose

- Own the `scheduler_settings_set.py` API endpoint.
- Persists scheduler-wide settings (currently just `catch_up_missed_runs`).
- Keep this file-level DOX profile synchronized with `scheduler_settings_set.py` because this directory is intentionally flat.

## Ownership

- `scheduler_settings_set.py` owns the runtime implementation.
- `scheduler_settings_set.py.dox.md` owns durable notes about responsibilities, contracts, side effects, and verification for that implementation.
- Classes:
- `SchedulerSettingsSet` (`ApiHandler`)
  - `async process(self, input: Input, request: Request) -> Output`

## Runtime Contracts

- HTTP handler deriving from `helpers.api.ApiHandler`; default auth/CSRF (no override) - this is a state-changing endpoint and must keep both.
- Request: `{"catch_up_missed_runs": bool}` - rejected with `{"ok": false, "error": ...}` if not a boolean.
- Response: `{"ok": true, "settings": {"catch_up_missed_runs": bool}}`.
- Update this file whenever the settings shape, validation, auth/CSRF requirements, or response contract changes.
- Observed side-effect areas: filesystem writes (via `helpers.task_scheduler.save_scheduler_settings`, `usr/scheduler/settings.json`), in-process settings cache update.
- Imported dependency areas include: `helpers.api`, `helpers.task_scheduler`.

## Verification

- `tests/test_task_scheduler_catchup.py` covers the underlying `SchedulerSettings`/`save_scheduler_settings` behavior this endpoint exposes.

## Child DOX Index

No child DOX files.

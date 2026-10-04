# scheduler_settings_get.py DOX

## Purpose

- Own the `scheduler_settings_get.py` API endpoint.
- Returns the current scheduler-wide settings (currently just `catch_up_missed_runs`).
- Keep this file-level DOX profile synchronized with `scheduler_settings_get.py` because this directory is intentionally flat.

## Ownership

- `scheduler_settings_get.py` owns the runtime implementation.
- `scheduler_settings_get.py.dox.md` owns durable notes about responsibilities, contracts, side effects, and verification for that implementation.
- Classes:
- `SchedulerSettingsGet` (`ApiHandler`)
  - `async process(self, input: Input, request: Request) -> Output`

## Runtime Contracts

- HTTP handler deriving from `helpers.api.ApiHandler`; default auth/CSRF (no override).
- Request: no required fields.
- Response: `{"ok": true, "settings": {"catch_up_missed_runs": bool}}`.
- Update this file whenever the settings shape, auth/CSRF requirements, or response contract changes.
- Observed side-effect areas: filesystem reads (via `helpers.task_scheduler.get_scheduler_settings`, `usr/scheduler/settings.json`).
- Imported dependency areas include: `helpers.api`, `helpers.task_scheduler`.

## Verification

- `tests/test_task_scheduler_catchup.py` covers the underlying `SchedulerSettings`/`get_scheduler_settings` behavior this endpoint exposes.

## Child DOX Index

No child DOX files.

# update_check.py DOX

## Purpose

- Own the `update_check.py` helper module.
- This module turns `helpers/windows_update.check()` into the update notification payload used by `extensions/python/user_message_ui/_10_update_check.py`: a notification only when a newer release of `JPChoom/agent-zero-windows` is published. It no longer contacts upstream's `api.agent-zero.ai` or sends an install ID.
- Keep this file-level DOX profile synchronized with `update_check.py` because this directory is intentionally flat.

## Ownership

- `update_check.py` owns the runtime implementation.
- `update_check.py.dox.md` owns durable notes about responsibilities, contracts, side effects, and verification for that implementation.
- Top-level functions:
- `async check_version()`

## Runtime Contracts

- Helper modules own reusable framework APIs and must preserve public callers unless all callers, tests, and docs are updated together.
- Update this file whenever public functions, classes, persistence behavior, path/security assumptions, side effects, or cross-module contracts change.
- Observed side-effect areas: network calls, settings/state persistence.
- Imported dependency areas include: `helpers.windows_update`.

## Key Concepts

- Called helpers: `windows_update.check`.
- Keep request/response, tool, or helper semantics documented here at the same time as source changes.

## Work Guidance

- Preserve public helper APIs used by core code and plugins unless every caller is updated.
- Keep path, auth, secret, persistence, network, and subprocess behavior explicit and bounded.
- Prefer adding cohesive helper functions here only when behavior is reused across modules.

## Verification

- Run targeted tests for changed helper behavior; run security regressions for auth, filesystem, WebSocket, tunnel, upload, or secret-handling helpers.
- `tests/test_windows_update.py` (`test_update_notification_only_when_a_newer_release_exists`).

## Child DOX Index

No child DOX files.

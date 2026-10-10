# workspace.py DOX

## Purpose

- Own the `workspace` API endpoint behind the Workspace view (`plugins/_workspace`).

## Ownership

- `workspace.py` owns the runtime implementation. Classes: `WorkspaceApi` (`ApiHandler`). Logic lives in `helpers/workspace.py`.

## Runtime Contracts

- POST JSON `{action, ...}`: `list` -> `{ok, resources, contexts, control_enabled}`; `adopt {id, context_id}` (the chat must exist); `release {id}`; `close {id}`. Each change returns the fresh list.
- `close` of an app needs Computer Use input enabled (`control_enabled`) and an untripped kill switch, writes a hash-chained `audit_log` record before acting, and ends the process through the cua-driver (`kill_app`); only apps tracked in the registry can be closed. `close` of a terminal (`terminal:<context>:<agent>:<session>`) ends that shell.
- Changes are audited to `usr/security_audit.jsonl` (`workspace_adopt`, `workspace_release`, `workspace_close`) with `by` (`local` or client IP, via `api/file_manager.caller`).
- Default auth + CSRF apply.

## Verification

- `pytest tests/test_workspace.py`

## Child DOX Index

No child DOX files.

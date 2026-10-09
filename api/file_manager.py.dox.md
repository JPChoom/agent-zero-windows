# file_manager.py DOX

## Purpose

- Own the `file_manager` API endpoint behind the Windows File Browser.

## Ownership

- `file_manager.py` owns the runtime implementation. Classes: `FileManager` (`ApiHandler`). Shared helper: `caller(request)` -> `(is_remote, who)`, also used by `file_manager_upload.py` and `file_manager_download.py`.
- Operations live in `helpers/file_manager.py`; the access policy in `helpers/file_access.py`.

## Runtime Contracts

- POST JSON `{action, ...}`: `places`, `list {path, show_hidden}`, `mkdir {path, name}`, `new_file {path, name}`, `rename {path, name}`, `delete {paths, permanent}`, `copy` / `move {paths, dest}`, `read_text {path}`, `write_text {path, content, encoding, expected_modified}`, `reveal {path}` (opens File Explorer on this PC; refused for remote sessions). Returns `{ok: true, ...}` or `{ok: false, error}`.
- Paths are absolute Windows paths. The policy comes from `file_access.policy_for(is_remote)`; remote = not `access_control.is_local_request`.
- Changes are audited to `usr/security_audit.jsonl` as `file_<action>` / `file_<action>_refused` with `by` (`local` or client IP).
- Default auth + CSRF apply.

## Verification

- `pytest tests/test_file_manager.py tests/test_file_access.py`

## Child DOX Index

No child DOX files.

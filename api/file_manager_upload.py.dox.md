# file_manager_upload.py DOX

## Purpose

- Own multipart uploads into a Windows File Browser folder.

## Ownership

- `file_manager_upload.py` owns the runtime implementation. Classes: `FileManagerUpload` (`ApiHandler`).

## Runtime Contracts

- POST multipart: `path` (absolute folder), `overwrite` (`"1"` replaces same-named files; otherwise `name (2)`), files in `files[]`. Only the base name of each upload is used. Each file goes through `file_manager.save_upload` under the caller's policy.
- Returns `{ok, saved: [paths], failed: [{name, error}]}`; audited as `file_upload`.
- Flask's `MAX_CONTENT_LENGTH` (5 GB, `helpers/ui_server.py`) caps a request. Default auth + CSRF apply.

## Verification

- `pytest tests/test_file_manager.py`

## Child DOX Index

No child DOX files.

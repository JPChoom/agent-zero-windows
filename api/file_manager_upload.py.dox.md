# file_manager_upload.py DOX

## Purpose

- Own multipart uploads into a Windows File Browser folder.

## Ownership

- `file_manager_upload.py` owns the runtime implementation. Classes: `FileManagerUpload` (`ApiHandler`).

## Runtime Contracts

- POST multipart: `path` (absolute folder), `overwrite` (`"1"` replaces same-named files; otherwise `name (2)`), files in `files[]`. Folder uploads add `relpaths[]` (one per file, `Folder/sub/name.ext`) and `dirs[]` (folders to create, so empty ones survive); subfolders are made with `file_manager.ensure_dir`, files saved with `file_manager.save_upload`, all under the caller's policy. A bad entry fails alone; the rest continue.
- Returns `{ok, saved: [paths], failed: [{name, error}], folders: [paths]}`; audited as `file_upload` (first 500 paths plus counts) and announced as `workdir_file_mutation_after` (action `upload`).
- Flask's `MAX_CONTENT_LENGTH` (5 GB, `helpers/ui_server.py`) caps a request. Default auth + CSRF apply.

## Verification

- `pytest tests/test_file_manager.py`

## Child DOX Index

No child DOX files.

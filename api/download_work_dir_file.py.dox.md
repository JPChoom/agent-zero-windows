# download_work_dir_file.py DOX

## Purpose

- Own the `/api/download_work_dir_file?path=` URL that chat attachments, message file links (`file://` in `webui/js/messages.js`) and Office documents (`plugins/_office/.../document-actions.js`) build.

## Ownership

- `download_work_dir_file.py` owns the runtime implementation. Classes: `DownloadFile` (`ApiHandler`, GET). Function: `make_disposition(name)` (RFC 5987 `Content-Disposition`, also used by `file_manager_download.py`).

## Runtime Contracts

- Accepts the old path forms (Docker-style `/a0/...`, `file://` URLs, workdir-relative, Windows paths), translates them with `helpers/file_manager.translate`, then serves them through `api/file_manager_download.serve_download`: the File Browser access policy applies (remote sessions use the remote cap), protected files are refused (403), folders arrive as a ZIP, and every download is audited.
- Default auth + CSRF (session cookie) apply.

## Verification

- `pytest tests/test_file_manager.py tests/test_office_canvas_setup.py`

## Child DOX Index

No child DOX files.

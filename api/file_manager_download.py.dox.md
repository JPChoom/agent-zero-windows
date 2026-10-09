# file_manager_download.py DOX

## Purpose

- Own File Browser downloads: a single file streamed as-is, or folders / several items as one ZIP.

## Ownership

- `file_manager_download.py` owns the runtime implementation. Classes: `FileManagerDownload` (`ApiHandler`, GET only).

## Runtime Contracts

- GET `?path=<abs>[&path=...][&inline=1]`, so the browser downloads natively (progress, no page memory). CSRF passes via the session cookie, as for the other GET endpoints.
- One file streams from disk; anything else is `file_manager.zip_selection` into a temp file, streamed and then deleted.
- `inline=1` (single file, for previews) sends `Content-Disposition: inline`; HTML, SVG and XHTML are served as `text/plain` so files from disk never run as pages in the app's origin. `nosniff` and `no-store` are always set.
- Refusals: 403 (outside the policy or protected) / 404. Every download and refusal is audited (`file_download`, `file_download_refused`).

## Verification

- `pytest tests/test_file_manager.py`

## Child DOX Index

No child DOX files.

# file_manager.py DOX

## Purpose

- Own the File Browser's operations on real Windows paths: listing, places, create, rename, delete, copy/move, upload, text read/write and ZIP downloads.

## Ownership

- `file_manager.py` owns the runtime implementation; this file owns its contracts.
- Public API: `FileOpError`, `list_dir`, `places`, `mkdir`, `new_file`, `rename`, `delete`, `transfer`, `save_upload`, `read_text`, `write_text`, `zip_selection`, `MAX_ENTRIES`, `MAX_TEXT_BYTES`.
- Callers: `api/file_manager.py`, `api/file_manager_upload.py`, `api/file_manager_download.py`.

## Runtime Contracts

- Every function takes the caller's `file_access.Policy` and checks every path with `file_access.resolve` / `resolve_new` before touching it.
- `list_dir`: protected entries never listed; hidden/system entries (attributes, or a leading dot) counted in `hidden_count` unless `show_hidden`; at most `MAX_ENTRIES`; `parent` is empty at the edge of the allowed area; links/junctions carry `is_link` and `outside`.
- `places`: Workdir, the A0 folder (or `usr`) and the user's known folders (`SHGetKnownFolderPath`, so OneDrive redirection is followed) when allowed; drives with `allowed` / `partly`. Remote sessions only see drives they can at least partly open.
- `delete` sends to the Recycle Bin (`SHFileOperationW`, `FOF_ALLOWUNDO`, no dialogs) unless `permanent` or the drive is removable/network (no Recycle Bin there; the result says `recycled: false`). It refuses drives, any policy root or its parents, and folders that contain protected files. `rename` / `transfer` refuse the latter too.
- Name conflicts: `mkdir` / `new_file` / `rename` refuse; copies, moves and uploads get Explorer-style `name (2).ext`; uploads replace only with `overwrite`, and write to a `.part-*` file first.
- Text: up to `MAX_TEXT_BYTES` (2 MB), binary refused; encoding detected (`utf-8-sig`, `utf-8`, `cp1252`, `latin-1`) and kept on save; line endings untouched; `expected_modified` refuses a save over a file changed on disk.
- `zip_selection` writes a temp ZIP (ZIP64) and re-checks every file's real path, so links/junctions inside a folder cannot add outside or protected files; locked files are skipped.

## Verification

- `pytest tests/test_file_manager.py tests/test_file_access.py`

## Child DOX Index

No child DOX files.

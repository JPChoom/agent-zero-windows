# file_browser.py DOX

## Purpose

- Own `list_directory_absolute(path)`, the folder-only listing behind the Settings folder picker (`api/get_folder_browser_files.py`, `webui/components/modals/folder-picker/`).

## Ownership

- `file_browser.py` owns the runtime implementation; this file owns its contracts.
- The File Browser is not here: operations live in `helpers/file_manager.py`, access rules in `helpers/file_access.py`.

## Runtime Contracts

- Deliberately unrestricted and folder-only: lists subfolders of any absolute path for an authenticated user picking a folder in Settings. Never wire it into an agent-facing endpoint or the File Browser.
- An empty path lists drive roots on Windows (`/` on POSIX); going up from a drive root returns an empty `parent_path` (back to the drive list).

## Verification

- Smoke-test the Settings folder picker.

## Child DOX Index

No child DOX files.

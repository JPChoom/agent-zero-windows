# get_folder_browser_files.py DOX

## Purpose

- List a directory's subfolders by absolute path for the folder picker used when configuring tiered filesystem access.

## Ownership

- `get_folder_browser_files.py` owns the runtime implementation; this file owns its contracts.
- Class: `GetFolderBrowserFiles`.

## Runtime Contracts

- Standard authenticated, CSRF-protected JSON POST handler (`helpers.api.ApiHandler`).
- Deliberately has no workdir containment check: it only lists folder names for the picker, never file contents. Keep it read-only and folders-only.
- Do not reuse it for file reads.

## Verification

- Smoke-test the folder picker in Settings.

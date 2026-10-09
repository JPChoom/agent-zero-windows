# windows_update.py DOX

## Purpose

- Own updating a native Windows install (a git clone) to a published release of Agent Zero for Windows.

## Ownership

- `windows_update.py` owns the runtime implementation; this file owns its contracts.
- Public API: `RELEASE_REPO`, `parse_version`, `is_newer`, `local_info`, `fetch_latest_release`, `check`, `apply`, `rollback`, `load_state`, `UpdateError`.
- Callers: `api/windows_update.py` (Settings > Check for updates), `helpers/update_check.py` (update notification).

## Runtime Contracts

- Releases come only from `RELEASE_REPO` (`JPChoom/agent-zero-windows`): `GET /repos/<repo>/releases/latest`, unauthenticated, cached `RELEASE_CACHE_SECONDS` (1 h). Drafts, pre-releases and tags not matching `TAG_PATTERN` (`vX.Y` or `vX.Y.Z`) are ignored. Nothing identifying the install is sent. A failed lookup returns `None` (`check_failed`), never raises.
- The installed version is `git describe --tags --abbrev=0`; `check()` also reports `current_describe` and a `note` when the checkout has commits beyond its tag.
- `apply(tag)` never discards work. It refuses (raises `UpdateError`) when the checkout is not a git repo, is not on `main`, has modified tracked files, or has commits the release lacks (not a fast-forward). Otherwise: fetch only that tag from `RELEASE_GIT_URL`, `git merge --ff-only <tag>`, then `pip install -r requirements.txt` with the running interpreter if the release changed `requirements.txt`; a failed install is undone with `git reset --keep`. `usr/` is git-ignored and never touched.
- State (`usr/windows_update.json`): `previous_head`, `previous_version`, `updated_to`, `applied_at_epoch`. `rollback()` returns to `previous_head` with `git reset --keep` (refuses with modified tracked files) and reinstalls requirements if they differ.
- `restart_pending` is true while the update was applied after this process started (psutil create time). New code runs only after `helpers/process.reload`.
- One apply/rollback at a time (`_apply_lock`).

## Verification

- `pytest tests/test_windows_update.py` (throwaway git repos stand in for GitHub and the install).

## Child DOX Index

No child DOX files.

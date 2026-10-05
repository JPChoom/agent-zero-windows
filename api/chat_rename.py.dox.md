# chat_rename.py DOX

## Purpose

- Manually set a chat's display name (the override for the automatic first-exchange name).

## Ownership

- `chat_rename.py` owns the runtime implementation; this file owns its contracts.
- Class: `RenameChat`.

## Runtime Contracts

- Standard authenticated, CSRF-protected JSON POST handler (`helpers.api.ApiHandler`).
- Whitespace (including multi-line pastes) is collapsed to single spaces; names longer than `MAX_NAME_LENGTH` (40, matching the automatic renamer) are truncated with `...`; missing/blank names and unknown context ids return `{ok: false, error}`.
- Persists with `persist_chat.save_tmp_chat` and marks chat lists dirty for every open tab.

## Verification

- `pytest tests/test_chat_rename_api.py`

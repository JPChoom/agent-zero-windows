# chat_trash.py DOX

## Purpose

- Own the chat trash ("Recently deleted"): deleted chats are moved, not erased, and stay restorable for `RETENTION_DAYS` (30).

## Ownership

- `chat_trash.py` owns the runtime implementation; this file owns its contracts.
- Public API: `trash_chat(ctxid, context=None) -> str | None`, `list_trash()`, `restore_chat(trash_id) -> str`, `purge(trash_id)`, `empty_trash() -> int`, `purge_expired() -> int`, `TrashError`.

## Runtime Contracts

- A trashed chat is its whole `usr/chats/<id>/` folder (chat.json + message files) moved to `usr/chats/.trash/<trash_id>/` with a `trash.json` (id, name, created_at, deleted_at).
- `trash_chat` must run before `context.reset()` (it flushes the latest state with `persist_chat.save_tmp_chat`); a never-saved chat has no folder and returns `None` (nothing to keep).
- `restore_chat` deserializes the chat back into memory; if the original id is taken (in memory or on disk) it restores under a new id and rewrites chat.json.
- Provider-stored responses are deleted only by `purge`/`empty_trash`/expiry (`persist_chat.delete_provider_responses_for_data`), so a restored chat can continue.
- Expiry is lazy: `purge_expired` runs on every `list_trash` and `trash_chat`; there is no background job.
- `trash_id` must match `[A-Za-z0-9_-]{1,64}`; anything else raises `TrashError` (no path traversal).
- `persist_chat.load_tmp_chats` / `saved_chat_ids` only read `usr/chats/*/chat.json`, so `.trash` is never loaded as a chat.
- Callers: `api/chat_remove.py` (trash on delete), `api/chat_trash.py` (list/restore/delete/empty).

## Verification

- `pytest tests/test_chat_trash.py`

## Child DOX Index

No child DOX files.

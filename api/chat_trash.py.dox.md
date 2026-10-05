# chat_trash.py DOX

## Purpose

- Own the `/chat_trash` endpoint behind the "Recently deleted" modal (`webui/components/modals/chat-trash/`).

## Ownership

- `chat_trash.py` owns the runtime implementation; this file owns its contracts.
- Classes: `ChatTrash` (`ApiHandler`) - `async process(self, input, request)`.

## Runtime Contracts

- Standard authenticated, CSRF-protected JSON POST.
- `action: "list"` -> `{items: [{trash_id, id, name, created_at, deleted_at, expires_at}], retention_days}` (newest first; expired entries purged first).
- `action: "restore", trash_id` -> `{ok, context_id}`; marks all chat lists dirty so every tab shows the restored chat.
- `action: "delete", trash_id` -> `{ok}` (permanent, deletes provider-stored responses).
- `action: "empty"` -> `{ok, deleted}`.
- Invalid ids / missing entries return HTTP 400 with a plain-text message (`chat_trash.TrashError`); unknown action -> 400.
- All storage logic lives in `helpers/chat_trash.py`.

## Verification

- `pytest tests/test_chat_trash.py`; smoke-test the modal (sidebar menu > Recently deleted) and the Undo toast after deleting a chat.

## Child DOX Index

No child DOX files.

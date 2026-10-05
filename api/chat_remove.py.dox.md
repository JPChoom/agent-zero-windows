# chat_remove.py DOX

## Purpose

- Own the `chat_remove.py` API endpoint.
- This module handles chat remove requests.
- Keep this file-level DOX profile synchronized with `chat_remove.py` because this directory is intentionally flat.

## Ownership

- `chat_remove.py` owns the runtime implementation.
- `chat_remove.py.dox.md` owns durable notes about responsibilities, contracts, side effects, and verification for that implementation.
- Classes:
- `RemoveChat` (`ApiHandler`)
  - `async process(self, input: Input, request: Request) -> Output`

## Runtime Contracts

- HTTP handlers must derive from `helpers.api.ApiHandler`; WebSocket handlers must derive from `helpers.ws.WsHandler`.
- Update this file whenever request payloads, authentication or CSRF requirements, response shapes, route side effects, or WebSocket event contracts change.
- `RemoveChat` is an `ApiHandler`.
- `RemoveChat` defines `process(...)`.
- Saved chats are moved to the trash (`helpers/chat_trash.trash_chat`, before `context.reset()`) and the response carries `trash_id` (null for a never-saved chat, which is erased via `persist_chat.remove_chat`). Provider-stored responses are kept until the trash entry is purged. Scheduled tasks of the chat are still removed.
- Observed side-effect areas: filesystem writes, filesystem deletion, settings/state persistence, scheduler state.
- Imported dependency areas include: `agent`, `helpers`, `helpers.api`, `helpers.task_scheduler`.

## Key Concepts

- Important called helpers/classes observed in the source: `scheduler.cancel_tasks_by_context`, `AgentContext.use`, `AgentContext.remove`, `persist_chat.remove_chat`, `scheduler.get_tasks_by_context_id`, `mark_dirty_all`, `context.reset`, `scheduler.reload`, `scheduler.remove_task_by_uuid`.
- Keep request/response, tool, or helper semantics documented here at the same time as source changes.

## Work Guidance

- Preserve authentication, CSRF, loopback, and API-key checks unless the endpoint contract explicitly changes.
- Update frontend callers, plugin callers, and tests together when payload shape changes.
- Use `helpers.api.Response` for non-JSON responses, files, redirects, or status-specific replies.

## Verification

- Run endpoint-specific or API/WebSocket tests for changed behavior; smoke-test browser callers when no focused test exists.
- Trash behavior: `pytest tests/test_chat_trash.py`.

## Child DOX Index

No child DOX files.

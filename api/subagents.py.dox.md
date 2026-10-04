# subagents.py DOX

## Purpose

- Own the `subagents.py` API endpoint.
- This module returns subordinate agent profile data for UI and delegation flows.
- Keep this file-level DOX profile synchronized with `subagents.py` because this directory is intentionally flat.

## Ownership

- `subagents.py` owns the runtime implementation.
- `subagents.py.dox.md` owns durable notes about responsibilities, contracts, side effects, and verification for that implementation.
- Classes:
- `Subagents` (`ApiHandler`)
  - `async process(self, input: Input, request: Request) -> Output`
  - `get_subagents_list(self)`
  - `load_agent(self, name: str | None)`
  - `save_agent(self, name: str | None, data: dict | None)`
  - `delete_agent(self, name: str | None)`

## Runtime Contracts

- HTTP handlers must derive from `helpers.api.ApiHandler`; WebSocket handlers must derive from `helpers.ws.WsHandler`.
- Update this file whenever request payloads, authentication or CSRF requirements, response shapes, route side effects, or WebSocket event contracts change.
- `Subagents` is an `ApiHandler`.
- `Subagents` defines `process(...)`.
- Request: `{"action": "list" | "load" | "save" | "delete", "name"?: str, "data"?: dict, "context_id"?: str}`. `load`/`save`/`delete` require `name`; `save` requires `data` (a `subagents.SubAgent`-shaped dict: `name`, `title`, `description`, `context`, `enabled`, `prompts`).
- Response: `{"ok": true, "data": ...}` or `{"ok": false, "error": str}`. `list` returns a list of plain dicts (`subagents.SubAgentListItem.model_dump()`); `load`/`save` return a single plain dict (`subagents.SubAgent.model_dump()`) - `helpers.api.ApiHandler.handle_request` serializes the response with plain `json.dumps`, which cannot encode Pydantic model instances directly, so every action here must return `.model_dump()`'d data, never the raw model.
- `save`/`delete` only ever affect `usr/agents/<name>/` (see `helpers.subagents.save_agent_data`/`delete_agent_data`); built-in profiles under `agents/` are never written or deleted through this endpoint.
- Observed side-effect areas: filesystem writes, filesystem deletion.
- Imported dependency areas include: `helpers`, `helpers.api`, `typing`.
- Frontend callers: `webui/components/settings/agent/agent-profiles.html` + `agent-profiles-store.js` (profile list/create/edit/delete UI added under Settings > Agent Config).

## Key Concepts

- Important called helpers/classes observed in the source: `subagents.get_agents_list`, `subagents.load_agent_data`, `subagents.SubAgent`, `subagents.save_agent_data`, `subagents.delete_agent_data`, `self.use_context`, `Exception`, `self.get_subagents_list`, `self.load_agent`, `self.save_agent`, `self.delete_agent`.
- Keep request/response, tool, or helper semantics documented here at the same time as source changes.

## Work Guidance

- Preserve authentication, CSRF, loopback, and API-key checks unless the endpoint contract explicitly changes.
- Update frontend callers, plugin callers, and tests together when payload shape changes.
- Use `helpers.api.Response` for non-JSON responses, files, redirects, or status-specific replies.

## Verification

- Run endpoint-specific or API/WebSocket tests for changed behavior; smoke-test browser callers when no focused test exists.
- Related tests observed by source search:
  - `tests/test_skills_runtime.py`

## Child DOX Index

No child DOX files.

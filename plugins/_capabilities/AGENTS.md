# Capabilities Plugin DOX

## Purpose

- Own capability policies: which tools and tool actions an agent may use at all, per scope, in every permission mode.

## Ownership

- `helpers/policy.py` owns capability ids, scope layering, the superior chain and the decisions.
- `extensions/python/tool_execute_before/_04_capabilities.py` owns the gate.
- `default_config.yaml`, `plugin.yaml` and `webui/config.html` own defaults, metadata and settings.

## Local Contracts

- A capability is `tool` or `tool:action` (`capability_id`: the action from the tool name, else the call's `action`, `method` or `runtime`). A bare tool pattern covers all its actions.
- A bundled profile can ship a limit in `agents/<profile>/capabilities.yaml` (the read-only `coding-reviewer` and `coding-diagnostician` do); it is one more layer, so settings can narrow it but never widen it.
- Every scope with a config (global, project, profile, project + profile) is a layer; a call must pass each: allowed by its `allow` (missing = everything) and denied by none. A subordinate is also bound by every agent above it. An unreadable config allows nothing.
- The gate runs at `_04`, before `_safety_policy` (`_05`) and `_permissions` (`_06`), is `FAIL_LOUD`, and holds in every permission mode. `response` is always allowed so a turn can end.
- Fully denied tools are left out of the system prompt (`extensions/python/system_prompt/_11_tools_prompt.py`, and the MCP section through `MCPConfig.get_tools_prompt(include=...)` in `_12_mcp_prompt.py`) and the native tool list (`helpers/responses_tools.py`, local and MCP); restrictions are listed for the model in a short notice.
- Bundled calls are checked per inner call (`calls_of`): a browser `multi` call's steps and a `parallel` call's tool calls.
- A parallel worker runs as a fresh top-level agent, so `helpers/parallel_tools.py` stores the starting agent's `scope_chain` on the job and in the worker context (`CONTEXT_SCOPES_KEY`); `scope_chain` includes inherited scopes, so a subordinate cannot escape its limits through `parallel`.
- Messaging chats (the governing chat's channel, `helpers/channels.channel_of`) also apply each layer's `messaging_deny` and `channels.<channel>` allow/deny.
- `api/known.py` lists tool names (prompt files, MCP) with `KNOWN_ACTIONS` for the settings screen.
- Defaults allow everything: nothing changes until a user sets a policy.

## Work Guidance

- Keep capability ids stable: users write them in settings.

## Verification

- `pytest tests/test_capabilities.py`.

## Child DOX Index

No child DOX files.

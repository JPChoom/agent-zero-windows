# A0 Connector Plugin DOX

## Purpose

- Own the current Agent Zero connector plugin for HTTP and WebSocket integration.
- Provide remote execution, text-editing freshness, and connector runtime bridges.

## Ownership

- `plugin.yaml` owns plugin metadata and settings scope.
- `api/` owns connector WebSocket and API entry points.
- `helpers/` owns chat context, event bridge, execution config, freshness, version, and WebSocket runtime helpers.
- `tools/`, `prompts/`, `skills/`, `extensions/`, and `webui/` own connector-facing agent and UI contributions.

## Local Contracts

- `computer_use_remote` refuses A0W's hard-blocked key combos (`plugins/_computer_use/helpers/policy.blocked_hotkey`) and checks the kill switch for input actions before contacting the CLI host.
- `code_execution_remote` passes the command safety floor (`plugins/_safety_policy`) and the kill switch like `code_execution_tool`: checked at `tool_execute_before` and again inside the tool for terminal/python/nodejs/input.

- Preserve session-auth and `auth.handlers` activation assumptions.
- Keep remote tool prompts synchronized with remote tool behavior and disclose
  them only from connected CLI metadata: no connected CLI hides all remote tool
  prompts, remote file metadata enables `text_editor_remote`, F4-enabled remote
  execution metadata enables `code_execution_remote`, and supported enabled
  Computer Use that does not need re-arming enables `computer_use_remote`.
- Do not bypass WebSocket authentication or leak connector session data.
- File operation results may arrive as chunked JSON/base64
  `connector_file_op_result` frames; resolve the pending file operation only
  after all chunks for the `op_id` are assembled.

## Work Guidance

- Coordinate connector runtime changes with API, tools, prompts, and WebUI viewer behavior together.

## Verification

- Run connector-specific tests or smoke-test HTTP and `/ws` integration when changing runtime behavior.

## Child DOX Index

No child DOX files.

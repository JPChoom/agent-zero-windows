# integration_commands.py DOX

## Purpose

- Own the `integration_commands.py` helper module.
- This module parses external integration slash commands such as project/config/send controls.
- Keep this file-level DOX profile synchronized with `integration_commands.py` because this directory is intentionally flat.

## Ownership

- `integration_commands.py` owns the runtime implementation.
- `integration_commands.py.dox.md` owns durable notes about responsibilities, contracts, side effects, and verification for that implementation.
- Top-level functions:
- `extract_command_line(text: str) -> str`
- `parse_command(text: str) -> tuple[str, str] | None`
- `try_handle_command(context: 'AgentContext', text: str) -> str | None`
- `_handle_queue(context: 'AgentContext', args: str) -> str`
- `_handle_project(context: 'AgentContext', args: str) -> str`
- `_handle_config(context: 'AgentContext', args: str) -> str`
- `_format_project_entry(item: dict) -> str`
- `_describe_project(items: list[dict], current_name: str) -> str`
- `_describe_override(override: dict | None) -> str`
- `_strip_quotes(value: str) -> str`
- `_normalize_lookup(value: str) -> str`
- `_match_named_item(items: list[dict], desired: str, keys: tuple[str, ...]) -> tuple[dict | None, list[dict]]`
- Notable constants/configuration names: `_CLEAR_VALUES`, `_SUPPORTED_COMMANDS`.

## Runtime Contracts

- Helper modules own reusable framework APIs and must preserve public callers unless all callers, tests, and docs are updated together.
- Update this file whenever public functions, classes, persistence behavior, path/security assumptions, side effects, or cross-module contracts change.
- Observed side-effect areas: filesystem writes, model calls, plugin state, settings/state persistence.
- Imported dependency areas include: `__future__`, `helpers`, `helpers.persist_chat`, `helpers.state_monitor_integration`, `plugins._model_config.helpers`, `re`, `typing`.
- `/agent` switches the top-level chat profile and preserves existing subordinate agent profiles.

## Key Concepts

- Important called helpers/classes observed in the source: `splitlines`, `extract_command_line`, `line.partition`, `command.strip.lower`, `parse_command`, `mq.get_queue`, `args.strip.lower`, `mq.send_all_aggregated`, `mark_dirty_for_context`, `_strip_quotes`, `_match_named_item`, `projects.activate_project`, `initialize_agent`, `model_config.is_chat_override_allowed`, `context.get_data`, `context.set_data`, `save_tmp_chat`, `str.strip`, `value.strip`, `value.lower.strip`, `re.sub`.
- Keep request/response, tool, or helper semantics documented here at the same time as source changes.

## Work Guidance

- Preserve public helper APIs used by core code and plugins unless every caller is updated.
- Keep path, auth, secret, persistence, network, and subprocess behavior explicit and bounded.
- Prefer adding cohesive helper functions here only when behavior is reused across modules.

## Verification

- Run targeted tests for changed helper behavior; run security regressions for auth, filesystem, WebSocket, tunnel, upload, or secret-handling helpers.
- Related tests observed by source search:
  - `tests/test_subagent_profiles.py`

## Child DOX Index

No child DOX files.

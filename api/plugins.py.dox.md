# plugins.py DOX

## Purpose

- Own the `plugins.py` API endpoint.
- This module manages plugin actions and plugin settings through the core API.
- Keep this file-level DOX profile synchronized with `plugins.py` because this directory is intentionally flat.

## Ownership

- `plugins.py` owns the runtime implementation.
- `plugins.py.dox.md` owns durable notes about responsibilities, contracts, side effects, and verification for that implementation.
- Classes:
- `Plugins` (`ApiHandler`)
  - `async process(self, input: dict, request: Request) -> dict | Response`

## Runtime Contracts

- HTTP handlers must derive from `helpers.api.ApiHandler`; WebSocket handlers must derive from `helpers.ws.WsHandler`.
- Update this file whenever request payloads, authentication or CSRF requirements, response shapes, route side effects, or WebSocket event contracts change.
- `Plugins` is an `ApiHandler`.
- `Plugins` defines `process(...)`.
- Observed side-effect areas: filesystem reads, filesystem writes, filesystem deletion, subprocess/runtime control, plugin state, settings/state persistence.
- Imported dependency areas include: `helpers`, `helpers.api`, `helpers.localization`, `json`, `os`, `subprocess`, `sys`.

## Key Concepts

- Important called helpers/classes observed in the source: `Response`, `plugins.find_plugin_assets`, `plugins.get_plugin_meta`, `plugins.get_default_plugin_config`, `plugins.save_plugin_config`, `plugins.toggle_plugin`, `plugins.find_plugin_dir`, `plugins.call_plugin_hook`, `files.get_abs_path`, `Localization.get.now_iso`, `plugins.determine_plugin_asset_path`, `self._get_config`, `self._get_toggle_status`, `self._list_configs`, `self._delete_config`, `self._delete_plugin`, `self._get_default_config`, `self._save_config`, `self._toggle_plugin`, `self._get_doc`, `self._run_execute_script`.
- `_get_config` has two branches: when a saved `config.json` exists it is read directly with `files.read_file_json` (this generic settings editor shows/edits exactly what's persisted); when none exists it falls back to `plugins.get_plugin_config(...)`, which runs that plugin's `get_plugin_config` hook. The direct-read branch now also runs `plugins.call_plugin_hook(plugin_name, "get_plugin_config", default=settings, ...)` on the loaded dict, so both branches see the same hook-backfilled shape - without this, a plugin that adds a new config key after some users already have a saved file (e.g. `_model_config`'s `vision_model`) would show that key as missing here even though every other read path (the plugin's own API endpoints, Python helpers) backfills it via the same hook.
- Keep request/response, tool, or helper semantics documented here at the same time as source changes.

## Work Guidance

- Preserve authentication, CSRF, loopback, and API-key checks unless the endpoint contract explicitly changes.
- Update frontend callers, plugin callers, and tests together when payload shape changes.
- Use `helpers.api.Response` for non-JSON responses, files, redirects, or status-specific replies.

## Verification

- Run endpoint-specific or API/WebSocket tests for changed behavior; smoke-test browser callers when no focused test exists.
- Related tests observed by source search:
  - `tests/test_a0_connector_computer_use_metadata.py`
  - `tests/test_a0_connector_prompt_gating.py`
  - `tests/test_browser_agent_regressions.py`
  - `tests/test_chat_compaction.py`
  - `tests/test_default_prompt_budget.py`
  - `tests/test_document_query_plugin.py`
  - `tests/test_error_retry_plugin.py`
  - `tests/test_host_browser_connector.py`

## Child DOX Index

No child DOX files.

# Model Configuration Plugin DOX

## Purpose

- Own LLM model selection, presets, API-key checks, scoped overrides, and model settings UI.

## Ownership

- `helpers/model_config.py` owns config resolution, presets, overrides, and runtime model object construction.
- `api/` owns model config, override, preset, search, and API-key endpoints.
- `webui/` owns model settings, summaries, switcher, and API-key UI.
- `default_config.yaml`, `default_presets.yaml`, `provider_metadata.yaml`, `hooks.py`, and `plugin.yaml` own defaults, metadata, hooks, and manifest.

## Local Contracts

- Preserve global, project, agent, and chat override resolution order.
- Project Settings `llm` payloads are owned here through the generic `helpers.projects` project extension-data hooks; keep project helper code agnostic to `_model_config` paths, presets, and inheritance rules.
- Keep provider metadata and API-key checks safe around secrets.
- Coordinate OAuth-backed providers with `_oauth` instead of hardcoding provider-specific auth here.
- `model_config_get` exposes `model_configured` as a derived chat-model readiness flag from provider, model name, and API-key availability.
- Applying a model preset may inherit durable tuning such as context windows and rate limits, but must replace or clear per-slot `kwargs` so provider-specific extra params never leak across model providers.
- Repair provider-specific model-config aliases at the model-config read/build boundary; keep provider-specific repairs out of provider-agnostic core wrappers such as `models.py`.
- `vision_model` is an optional fourth slot (alongside chat/utility/embedding): a sidecar model `tools/vision_load.py` calls to caption an image when the Main model's own `vision` flag is false. Unlike chat/utility, it has no per-chat override or preset resolution (`get_vision_model_config`/`build_vision_model` are simple passthroughs) - it is a single global fallback. `hooks.py`'s `get_plugin_config` hook backfills a missing `vision_model` key from `default_config.yaml` for every config read through the generic `helpers.plugins.get_plugin_config()` path (settings UI, model_config helpers, everything) - a saved config.json from before this slot existed is otherwise returned as-is, with no merge against current defaults. `model_config_set` and `hooks.py`'s `save_plugin_config` must keep `vision_model` in the same per-slot cleanup/extraction lists as the other three slots.

## Work Guidance

- Keep backend model config shape and frontend settings fields synchronized.

## Verification

- Run model-config and onboarding-related tests when model provider, preset, or API-key behavior changes.

## Child DOX Index

No child DOX files.

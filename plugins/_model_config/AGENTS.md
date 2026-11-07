# Model Configuration Plugin DOX

## Purpose

- Own LLM model selection, presets, API-key checks, scoped overrides, and model settings UI.

## Ownership

- `helpers/model_config.py` owns config resolution, presets, overrides, and runtime model object construction.
- `helpers/job_routing.py` owns which model runs which job and the Utility fallback; `helpers/tool_digest.py` owns shortening long tool results; `helpers/decision_shadow.py` owns the decision model in shadow mode.
- `api/` owns model config, override, preset, search, and API-key endpoints.
- `webui/` owns model settings, summaries, switcher, and API-key UI.
- `default_config.yaml`, `default_presets.yaml`, `provider_metadata.yaml`, `hooks.py`, and `plugin.yaml` own defaults, metadata, hooks, and manifest.

## Local Contracts

- `single_model_mode`: the Utility slot uses the Main model's identity fields (keeping its own `ctx_input` and rate limits) and `is_vision_model_configured` is False (no separate sidecar).
- `build_utility_model` runs the Utility slot through `utility_kwargs`: on `lm_studio` it uses the chat-completions route with `extra_body.reasoning_effort = "none"`, on `llama_cpp` the chat-completions route with `extra_body.chat_template_kwargs.enable_thinking = false` (needs `--jinja`) so reasoning models answer instead of thinking past the 180 s utility timeout (slot kwargs override).
- The `build_*_model` helpers tag each wrapper with `a0_perf_role` (`main`, `utility`, `vision`) so `helpers/perf.py` can tell which slot a model call came from.
- `sampling` (temperature, top_p, top_k, repeat_penalty; empty = provider default) is merged into Main/Utility kwargs by `apply_sampling`; a model's own kwargs win. top_k and repeat_penalty go in `extra_body` and only to `LOCAL_SAMPLING_PROVIDERS`.
- Dynamic sampling is EXPERIMENTAL and off by default (`sampling.dynamic`): `extensions/python/chat_model_call_before/_20_dynamic_sampling.py` adjusts only unlocked values on the per-call model object, using the visible `sampling.dynamic_rules`; `helpers/dynamic_sampling.py` holds the pure classify/adjust logic. The UI asks for confirmation before enabling it.
- `hooks.py get_plugin_config` backfills `BACKFILLED_KEYS` into configs saved before they existed.
- `job_routing` (Settings > Models > Background jobs): `get_utility_model` goes through `job_routing.utility_model_for_call`. The job comes from `perf.CALLER`, so a new job needs a `perf.tagged` name in `JOBS` and a row in `webui/config.html`. `fallback_to_main` wraps the model in `RoutedUtilityModel`: a TCP check first, then one retry on Main for any failure except a stop, `Preempted`, or an answer already streaming; only outages (`_is_outage`) mark the server down. A refused request (over context) moves that job alone. Nothing wraps when Utility is the Main model. `banners/_40_utility_fallback.py` shows while a server is marked down.
- `subordinate_profiles`: `get_chat_model_config` gives a listed subordinate the Utility model with Main's limits (`subordinate_on_utility`, `_subordinate_slot`); `routed=False` is always the real Main model. Never the main agent, and never a call tagged `infection_check*`: the safety check stays on its own model. `chat_model_call_before/_10_subordinate_route.py` returns it to Main when the server is away.
- `job_routing.decision_shadow` (off by default): a decision model predicts beside each Main step (`thinking`) and each `call_subordinate` (`subordinate`) through `POST <api_base>/systemone`, in hooks that start a task and return. Verdicts, timings and an input hash go to `usr/perf/decision_shadow.jsonl`, never text; `tests/manual/decision_shadow_report.py` compares them with what happened. Nothing may read a prediction back into a decision: acting on one is a separate, measured change behind its own setting. Never use it for the safety check.
- `tool_digest` is EXPERIMENTAL and off by default: `tool_execute_after/_90_tool_digest.py` replaces the middle of a long result, after the secret mask and completion gate. Head and tail stay word for word, the full text goes in the chat's folder, and any problem keeps the original. It never runs on Main (`UTILITY_ONLY_CALLERS`). The result stays untrusted by tool name in `hist_add_tool_result`; do not exempt it.

- Preserve global, project, agent, and chat override resolution order.
- Project Settings `llm` payloads are owned here through the generic `helpers.projects` project extension-data hooks; keep project helper code agnostic to `_model_config` paths, presets, and inheritance rules.
- Keep provider metadata and API-key checks safe around secrets.
- Coordinate OAuth-backed providers with `_oauth` instead of hardcoding provider-specific auth here.
- `model_config_get` exposes `model_configured` as a derived chat-model readiness flag from provider, model name, and API-key availability.
- Applying a model preset may inherit durable tuning such as context windows and rate limits, but must replace or clear per-slot `kwargs` so provider-specific extra params never leak across model providers.
- Repair provider-specific model-config aliases at the model-config read/build boundary; keep provider-specific repairs out of provider-agnostic core wrappers such as `models.py`.
- `vision_model` is an optional fourth slot (alongside chat/utility/embedding): a sidecar model `tools/vision_load.py` calls to caption an image when the Main model's own `vision` flag is false. Unlike chat/utility, it has no per-chat override or preset resolution (`get_vision_model_config`/`build_vision_model` are simple passthroughs) - it is a single global fallback. `hooks.py`'s `get_plugin_config` hook backfills a missing `vision_model` key from `default_config.yaml` for every config read through the generic `helpers.plugins.get_plugin_config()` path (settings UI, model_config helpers, everything) - a saved config.json from before this slot existed is otherwise returned as-is, with no merge against current defaults. `model_config_set` and `hooks.py`'s `save_plugin_config` must keep `vision_model` in the same per-slot cleanup/extraction lists as the other three slots.

- `local_server` (Local model server, `webui/local-server.html`): settings of the llama.cpp server Agent Zero runs (logic in `helpers/local_server.py`, process in `helpers/llama_server.py`, control `api/llama_server.py`). Picking a model sets Main - and Utility, unless "Also use it for the Utility model" is unticked - to `llama_cpp` with the model's alias and this server's address, and Main's vision to the Vision toggle; while Main runs on the server, its context length is the server's. The Vision field shows how much GPU memory the projector needs against what is free while the model runs without it (`model_info.mmproj_need_mib`, `gpu_free_mib`) and warns when it will not fit; the Server field shows the supervisor's `memory_warning`. "Prompt cache (RAM)" (`prompt_cache_mib`, Advanced, 0 = automatic) sets llama-server's `--cache-ram`. "Thinking limit" (`thinking_budget`, hidden for the Custom preset) caps a thinking model's thinking on the server. Start/Restart/Stop act on the saved settings; a running server picks up saved changes within a minute (job loop).

- `thinking` (`on` default / `off` / `auto` EXPERIMENTAL, `helpers/thinking.py`, hook `chat_model_call_before/_25_thinking.py`): turns the Main model's thinking off per call on llama.cpp (`chat_template_kwargs.enable_thinking`) and LM Studio (`reasoning_effort: none`, chat-completions route); `auto` thinks on iteration 0 and after a step whose last message looks like trouble (error, denied, traceback, misformat, timeout...). Other providers are not changed.

## Work Guidance

- Keep backend model config shape and frontend settings fields synchronized.

## Verification

- Run model-config and onboarding-related tests when model provider, preset, or API-key behavior changes.

## Child DOX Index

No child DOX files.

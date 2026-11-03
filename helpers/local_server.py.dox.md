# local_server.py DOX

## Purpose

- Own the settings side of the local model server: the `local_server` block of the model config (plugins/_model_config), presets, model discovery, the GGUF MTP check, and migration from the former `_llama_server` plugin.

## Ownership

- Public API: `settings(cfg)`, `server_config(cfg) -> llama_server.ServerConfig`, `preset_args(preset, model_path, extra_args)`, `thinking_args(preset, budget)`, `list_models(settings)`, `model_folders`, `mmproj_for(model_path)`, `has_mtp(model_path)`, `migrated_settings()`, `DEFAULTS`, `PRESETS`, `FAST_FLAGS`, `LOW_MEMORY_FLAGS`, `MTP_FLAGS`, `THINKING_BUDGET_MESSAGE`.

## Runtime Contracts

- Presets: `coding` = `FAST_FLAGS` + `MTP_FLAGS` only when `has_mtp` (a `<arch>.nextn_predict_layers` > 0 in the GGUF header, cached per path and mtime); `balanced` = `FAST_FLAGS`; `low_memory` = 4-bit KV; `custom` = `extra_args` through `llama_server.parse_extra_args` (forbidden arguments refused). Changing `FAST_FLAGS`/`MTP_FLAGS` changes the running server's identity, so it restarts.
- Prompt cache: `prompt_cache_mib` (0 = automatic: `PROMPT_CACHE_SHARE` of system RAM, between 8192 and `PROMPT_CACHE_MAX_MIB`) adds `--cache-ram N` for every preset except `custom` (`cache_args`). Main and utility calls share one slot, so the RAM cache is what brings a chat's conversation back after a safety-check or memory call instead of re-reading it (2026-11-02: 46% of requests re-read almost the whole prompt at the 8 GB default). `--cache-reuse` in the presets is disabled by llama-server for hybrid models such as Qwen3.8.
- Thinking limit: `thinking_budget` (default 6144 tokens, 0 = none) adds `--reasoning-budget N --reasoning-budget-message THINKING_BUDGET_MESSAGE` for every preset except `custom` (`thinking_args`), so thinking cannot run until the context window is full and the reply comes back empty.
- Context size: the Main slot's `ctx_length` while Main uses this server (`llama_cpp` provider at this port, or a blank address with port 8090); else `context_size`.
- Vision: `--mmproj <projector>` when `vision` is on: `mmproj_path` if it names a file, else `mmproj_for(model)` - the only mmproj-*.gguf next to the model, or with several the one sharing the most name words with the model (quantization words ignored), or none when nothing matches (never a guess).
- Models are listed from `usr/llama-cpp/models`, the LM Studio folder (`~/.lmstudio/models`) and `model_folders`; projectors, embedding and reranker files are left out.
- Migration: `plugins/_model_config/hooks.py` backfills a missing `local_server` with `migrated_settings()` (the old `usr/plugins/_llama_server/config.json`, empty or known flag sets mapped to presets, anything else to `custom`), else `DEFAULTS`.

## Verification

- `pytest tests/test_local_server.py`

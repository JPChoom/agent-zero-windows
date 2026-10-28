# local_server.py DOX

## Purpose

- Own the settings side of the local model server: the `local_server` block of the model config (plugins/_model_config), presets, model discovery, the GGUF MTP check, and migration from the former `_llama_server` plugin.

## Ownership

- Public API: `settings(cfg)`, `server_config(cfg) -> llama_server.ServerConfig`, `preset_args(preset, model_path, extra_args)`, `list_models(settings)`, `model_folders`, `mmproj_for(model_path)`, `has_mtp(model_path)`, `migrated_settings()`, `DEFAULTS`, `PRESETS`, `FAST_FLAGS`, `LOW_MEMORY_FLAGS`, `MTP_FLAGS`.

## Runtime Contracts

- Presets: `coding` = `FAST_FLAGS` + `MTP_FLAGS` only when `has_mtp` (a `<arch>.nextn_predict_layers` > 0 in the GGUF header, cached per path and mtime); `balanced` = `FAST_FLAGS`; `low_memory` = 4-bit KV; `custom` = `extra_args` through `llama_server.parse_extra_args` (forbidden arguments refused). Changing `FAST_FLAGS`/`MTP_FLAGS` changes the running server's identity, so it restarts.
- Context size: the Main slot's `ctx_length` while Main uses this server (`llama_cpp` provider at this port, or a blank address with port 8090); else `context_size`.
- Vision: `--mmproj <projector>` when `vision` is on: `mmproj_path` if it names a file, else `mmproj_for(model)` - the only mmproj-*.gguf next to the model, or with several the one sharing the most name words with the model (quantization words ignored), or none when nothing matches (never a guess).
- Models are listed from `usr/llama-cpp/models`, the LM Studio folder (`~/.lmstudio/models`) and `model_folders`; projectors, embedding and reranker files are left out.
- Migration: `plugins/_model_config/hooks.py` backfills a missing `local_server` with `migrated_settings()` (the old `usr/plugins/_llama_server/config.json`, empty or known flag sets mapped to presets, anything else to `custom`), else `DEFAULTS`.

## Verification

- `pytest tests/test_local_server.py`

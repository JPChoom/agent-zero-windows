# llama_server.py DOX

## Purpose

- Own the control endpoint of the local model server (Settings > Agent > Models > Local model server).

## Ownership

- `LlamaServer.process` with `action`: `status` / `models` (state plus lists), `start`, `restart`, `stop`, `model_info` (`path` -> `has_mtp`, `mmproj`), `download_plan`, `download` (`variant`).
- Every reply carries `status`, `installed`, `binary_exists`, `models`, `folders`, `own_models_dir`, `suggested_variant`, `gpu_total_mib`.

## Runtime Contracts

- Signed-in, CSRF-checked WebUI endpoint (ApiHandler defaults).
- Start and restart use the *saved* settings (`helpers/local_server.server_config()`), never values sent by the browser.
- `download_plan` and `download` are refused unless the request comes from this PC (`access_control.is_local_request`; tunnel clients are not local); `download` is refused while the server runs.
- Errors from the supervisor or the download are returned as `ok: false` with their message.

## Verification

- `pytest tests/test_local_server.py`

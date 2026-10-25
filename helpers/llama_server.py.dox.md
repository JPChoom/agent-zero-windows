# llama_server.py DOX

## Purpose

- Own the one supervised `llama-server.exe` process per A0W instance (Settings > Agent > Models > Local model server).

## Ownership

- Public API: `ServerConfig` (`command()`, `identity()`, `alias` = model file stem), `Supervisor` via `get()` (`start`, `stop`, `status`, `running_identity`), `config_from_settings(dict)` (flat settings dict, kept for scripts), `parse_extra_args`, `default_binary`, `port_in_use`, `wait_port_free`, `free_vram_mib`, `SupervisorError`.
- Settings come from `helpers/local_server.server_config()`; control is `api/llama_server.py`; autostart and applying saved changes is `extensions/python/job_loop/_40_llama_server.py`.

## Runtime Contracts

- Listens on 127.0.0.1 only; host, port, path, TLS files, model and alias are set here and refused in extra arguments (`FORBIDDEN_ARGS`).
- "Running" = the process we started (pid + start time) is alive, `/health` is ready and `/v1/models` lists our alias.
- Refuses to start when the binary or model is missing, the port is used by another program, or (NVIDIA) free VRAM is clearly too small (`VRAM_HEADROOM`).
- Crash recovery with `RESTART_BACKOFF`, at most `MAX_RESTARTS` per `RESTART_WINDOW`, then a notification. Stopped at A0W exit (`atexit`). A leftover from a killed A0W is adopted when identical and healthy, else stopped; after stopping it, `_launch` waits up to `PORT_RELEASE_SECONDS` (checked by binding) for the port.
- State in `usr/llama-cpp/server.json`, log in `usr/logs/llama-server.log` (rotated at `LOG_MAX_BYTES`).

## Verification

- `pytest tests/test_llama_server_supervisor.py` (real processes against `tests/fixtures/fake_llama_server.py`).

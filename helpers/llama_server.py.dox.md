# llama_server.py DOX

## Purpose

- Own the one supervised `llama-server.exe` process per A0W instance (Settings > Agent > Models > Local model server).

## Ownership

- Public API: `ServerConfig` (`command()`, `identity()`, `alias` = model file stem), `Supervisor` via `get()` (`start`, `stop`, `status`, `running_identity`), `config_from_settings(dict)` (flat settings dict, kept for scripts), `parse_extra_args`, `default_binary`, `port_in_use`, `wait_port_free`, `free_vram_mib`, `mmproj_of(config)`, `gpu_shared_mib(pid)`, `spill_message`, `MMPROJ_EXTRA_MIB`, `SupervisorError`. `status()` also carries `vision` and `memory_warning`.
- Settings come from `helpers/local_server.server_config()`; control is `api/llama_server.py`; autostart and applying saved changes is `extensions/python/job_loop/_40_llama_server.py`.

## Runtime Contracts

- API key: `ServerConfig.api_key_file` adds `--api-key-file`; `ensure_api_key()` creates `usr/llama-cpp/api_key.txt` once (a random key, so the server's identity stays the same across starts), `current_api_key()` reads it without creating it, and `_http_json` sends it. Every endpoint except `/health` refuses calls without it. `--api-key` and `--api-key-file` are refused in extra arguments.
- Listens on 127.0.0.1 only; host, port, path, TLS files, model and alias are set here and refused in extra arguments (`FORBIDDEN_ARGS`).
- "Running" = the process we started (pid + start time) is alive, `/health` is ready and `/v1/models` lists our alias.
- Refuses to start when the binary or model is missing, the port is used by another program, or (NVIDIA) free VRAM is clearly too small (`VRAM_HEADROOM`; with `--mmproj` the projector file plus `MMPROJ_EXTRA_MIB` is added).
- Memory check: `SPILL_SETTLE_SECONDS` after ready (or adoption), Windows' `GPU Process Memory` counters report the server's shared (system RAM) GPU memory; over `SPILL_WARN_MIB` (600; a server that fits shows ~270-320 MiB of driver host buffers, the measured Vision spill was 832) the model did not fit (it runs ~10x slower and calls stall), so `memory_warning` is set and a warning notification sent. English counter names only; `None` (no check) otherwise.
- Crash recovery with `RESTART_BACKOFF`, at most `MAX_RESTARTS` per `RESTART_WINDOW`, then a notification. Stopped at A0W exit (`atexit`), and on Windows every started or adopted server is assigned to a kill-on-close Job Object held by A0W's process (`_end_with_this_process`), so Windows ends it however A0W ends (console window closed, crash, Task Manager). An in-app restart (`os.execv`) therefore reloads the model too. A leftover from a killed A0W is adopted when identical and healthy, else stopped; after stopping it, `_launch` waits up to `PORT_RELEASE_SECONDS` (checked by binding) for the port.
- State in `usr/llama-cpp/server.json`, log in `usr/logs/llama-server.log` (rotated at `LOG_MAX_BYTES`).

## Verification

- `pytest tests/test_llama_server_supervisor.py` (real processes against `tests/fixtures/fake_llama_server.py`).

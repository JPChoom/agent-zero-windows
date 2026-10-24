# llama.cpp Server Plugin DOX

## Purpose

- Own the managed local llama.cpp server: Agent Zero starts, watches and stops `llama-server.exe` as one more model provider (`llama_cpp` in `conf/model_providers.yaml`, default `http://127.0.0.1:8090/v1`). LM Studio and every other provider stay first-class.

## Ownership

- `helpers/supervisor.py` owns the process: launch (hidden, `127.0.0.1` only), readiness and model-identity checks, VRAM check, crash recovery with backoff, stop, adoption or replacement of a server left by a forced kill, the state file `usr/llama-cpp/server.json` and the log `usr/logs/llama-server.log`.
- `helpers/download.py` owns installing the official Windows build into `usr/llama-cpp/bin/` (user-triggered only).
- `api/llama_server.py` owns status/start/stop/restart/download for the settings UI; `webui/config.html` the settings page.
- `extensions/python/job_loop/_40_llama_server.py` starts the server once per Agent Zero start when `autostart` is on.

## Local Contracts

- "Running" means: our process (pid + start time), `/health` ready, and `/v1/models` reports the alias we passed (the model file's stem). A port that merely answers is never enough.
- The supervisor owns host, port, model and alias; `extra_args` cannot override them (`FORBIDDEN_ARGS`), so the server can never listen beyond 127.0.0.1.
- Crash recovery restarts with `RESTART_BACKOFF` and gives up after `MAX_RESTARTS` in `RESTART_WINDOW`, notifying the user; autostart does not retry a failed server.
- No orphans: the server is stopped at Agent Zero exit (`atexit`); a leftover from a forced kill is adopted on the next start when identical and healthy, otherwise stopped.
- Upstream publishes every build as a GitHub pre-release, so the download takes the newest non-draft release (pre-releases included) that has the requested Windows build (`newest_release_with`); a missing digest or unexpected host on that build is an error, never a reason to fall back to an older one. Builds: cuda (plus the CUDA runtime archive), vulkan, rocm, cpu.
- Download is only run on an explicit user click (or the installer's `-Llama` choice), only from a local (not tunnel) session, only from `github.com/ggml-org/llama.cpp` releases, and only when the asset's SHA-256 published by GitHub matches; archives are zip-slip checked. Models are never downloaded or bundled.
- Status reads take no lock (a start can hold it for minutes while loading).

- After replacing a leftover server, `_launch` waits up to `PORT_RELEASE_SECONDS` for the port to be free (checked by binding, not connecting: a busy listener that never accepts fills its backlog and then refuses connects) before reporting the port as taken by another program.

## Verification

- `pytest tests/test_llama_server_supervisor.py tests/test_llama_server_plugin.py` (a Python stand-in for llama-server; no download, no GPU).
- On a real machine: download a build, pick a GGUF, Start; the llama.cpp provider answers a chat; kill Agent Zero with Task Manager and start it again (the server is adopted or replaced, never orphaned).

## Child DOX Index

No child DOX files.

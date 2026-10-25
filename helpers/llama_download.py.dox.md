# llama_download.py DOX

## Purpose

- Own downloading and installing the official `llama-server.exe` build.

## Ownership

- Public API: `plan(variant)`, `download(variant)`, `installed()`, `suggested_variant()`, `bin_dir()`, `select_assets`, `newest_release_with`, `extract`, `DownloadError`.

## Runtime Contracts

- Only assets of github.com/ggml-org/llama.cpp over HTTPS; the release API's SHA-256 `digest` must exist and match the bytes; archives must contain `llama-server.exe` and nothing outside the target folder (zip-slip check). Variants: cuda (with the cudart runtime archive), vulkan, rocm, cpu; upstream publishes builds as pre-releases, so the newest release that has the build is used.
- Installs into `usr/llama-cpp/bin/`, records the release in `usr/llama-cpp/installed.json`.
- Only ever run on the user's request: `api/llama_server.py` allows it from this PC only (`access_control.is_local_request`).

## Verification

- `pytest tests/test_local_server.py` (release data and archives built in the test, no network).

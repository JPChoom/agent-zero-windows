"""Status and control of the local model server (llama.cpp).

Signed-in, CSRF-checked WebUI only. Settings are the `local_server` part of
the model config (Settings > Agent > Models), read as saved: save first,
then start or restart.
"""

from __future__ import annotations

import asyncio
import os

from helpers import access_control, llama_download, llama_server, local_server
from helpers.api import ApiHandler, Request


class LlamaServer(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        action = str(input.get("action") or "status").strip().lower()
        sup = llama_server.get()
        try:
            if action in ("status", "models"):
                pass
            elif action in ("start", "restart"):
                config = local_server.server_config()
                if action == "restart":
                    await asyncio.to_thread(sup.stop)
                await asyncio.to_thread(sup.start, config)
            elif action == "stop":
                await asyncio.to_thread(sup.stop)
            elif action == "model_info":
                path = str(input.get("path") or "")
                return {**self._reply(True), "model_info": {
                    "path": path,
                    "has_mtp": await asyncio.to_thread(local_server.has_mtp, path),
                    "mmproj": local_server.mmproj_for(path),
                }}
            elif action in ("download_plan", "download"):
                # Installing a program is local-only: a remote session cannot
                # make this PC download and install a binary.
                if not access_control.is_local_request(getattr(request, "remote_addr", None), request.headers):
                    return self._reply(False, "Downloading llama-server is only possible on this PC, not remotely.")
                variant = str(input.get("variant") or local_server.settings().get("download_variant") or "")
                if action == "download_plan":
                    return {**self._reply(True), "plan": await asyncio.to_thread(llama_download.plan, variant)}
                if sup.status()["state"] in ("running", "starting"):
                    return self._reply(False, "Stop the server before replacing llama-server.")
                await asyncio.to_thread(llama_download.download, variant)
            else:
                return self._reply(False, f"Unknown action {action!r}.")
        except (llama_server.SupervisorError, llama_download.DownloadError) as exc:
            return self._reply(False, str(exc))
        except Exception as exc:
            return self._reply(False, f"{type(exc).__name__}: {exc}")
        return self._reply(True)

    def _reply(self, ok: bool, error: str = "") -> dict:
        s = local_server.settings()
        binary = str(s.get("binary_path") or "").strip() or llama_server.default_binary()
        return {
            "ok": ok,
            "error": error,
            "status": llama_server.get().status(),
            "installed": llama_download.installed(),
            "binary_exists": os.path.isfile(binary),
            "models": local_server.list_models(s),
            "folders": [{"label": label, "path": path} for label, path in local_server.model_folders(s)],
            "own_models_dir": local_server.own_models_dir(),
            "suggested_variant": llama_download.suggested_variant(),
            "gpu_total_mib": _gpu_total_mib(),
        }


def _gpu_total_mib() -> int | None:
    import shutil
    import subprocess

    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5, creationflags=0x08000000).stdout
        return int(out.strip().splitlines()[0])
    except Exception:
        return None

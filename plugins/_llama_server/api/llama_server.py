"""Status and control of the managed llama.cpp server (signed-in, CSRF-checked WebUI only)."""

from __future__ import annotations

import asyncio
import os

from helpers import access_control, files, plugins
from helpers.api import ApiHandler, Request
from plugins._llama_server.helpers import download, supervisor


def _settings() -> dict:
    return plugins.get_plugin_config("_llama_server") or {}


def models_dir() -> str:
    return files.get_abs_path("usr", "llama-cpp", "models")


def list_models() -> list[dict]:
    folder = models_dir()
    if not os.path.isdir(folder):
        return []
    items = []
    for root, _, names in os.walk(folder):
        for name in names:
            if name.lower().endswith(".gguf"):
                path = os.path.join(root, name)
                items.append({"name": os.path.relpath(path, folder), "path": path,
                              "size_mb": round(os.path.getsize(path) / (1024 * 1024))})
    return sorted(items, key=lambda m: m["name"].lower())


class LlamaServer(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        action = str(input.get("action") or "status").strip().lower()
        sup = supervisor.get()
        try:
            if action == "status":
                pass
            elif action in ("start", "restart"):
                config = supervisor.config_from_settings(_settings())
                if action == "restart":
                    await asyncio.to_thread(sup.stop)
                await asyncio.to_thread(sup.start, config)
            elif action == "stop":
                await asyncio.to_thread(sup.stop)
            elif action in ("download_plan", "download"):
                # Installing a program is local-only: a remote session cannot
                # make this PC download and install a binary.
                if not access_control.is_local_request(getattr(request, "remote_addr", None), request.headers):
                    return self._reply(False, "Downloading llama-server is only possible on this PC, not remotely.")
                variant = str(input.get("variant") or _settings().get("download_variant") or "")
                if action == "download_plan":
                    return {**self._reply(True), "plan": await asyncio.to_thread(download.plan, variant)}
                if sup.status()["state"] in ("running", "starting"):
                    return self._reply(False, "Stop the server before replacing llama-server.")
                await asyncio.to_thread(download.download, variant)
            else:
                return self._reply(False, f"Unknown action {action!r}.")
        except (supervisor.SupervisorError, download.DownloadError) as exc:
            return self._reply(False, str(exc))
        except Exception as exc:
            return self._reply(False, f"{type(exc).__name__}: {exc}")
        return self._reply(True)

    def _reply(self, ok: bool, error: str = "") -> dict:
        return {
            "ok": ok,
            "error": error,
            "status": supervisor.get().status(),
            "installed": download.installed(),
            "binary_exists": os.path.isfile(supervisor.config_from_settings(_settings()).binary)
            if self._safe_config() else False,
            "models": list_models(),
            "models_dir": models_dir(),
            "suggested_variant": download.suggested_variant(),
        }

    def _safe_config(self) -> bool:
        try:
            supervisor.config_from_settings(_settings())
            return True
        except supervisor.SupervisorError:
            return False

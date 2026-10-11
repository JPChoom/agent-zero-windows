"""Start the managed llama.cpp server when autostart is on.

The job loop runs about once a minute. A server that failed (for example it
kept crashing) is not retried here; the user restarts it from Settings after
fixing the cause. Crash recovery while running is the supervisor's own job.
"""

import asyncio

from helpers import plugins
from helpers.extension import Extension
from helpers.print_style import PrintStyle
from plugins._llama_server.helpers import supervisor

_tried = {"done": False}


class LlamaServerAutostart(Extension):
    async def execute(self, **kwargs):
        if _tried["done"]:
            return
        cfg = plugins.get_plugin_config("_llama_server") or {}
        if not cfg.get("autostart"):
            return
        _tried["done"] = True  # once per Agent Zero start
        sup = supervisor.get()
        if sup.status()["state"] in ("running", "starting"):
            return
        try:
            await asyncio.to_thread(sup.start, supervisor.config_from_settings(cfg))
            PrintStyle.success(f"llama.cpp server running at {sup.status()['api_base']}")
        except supervisor.SupervisorError as exc:
            PrintStyle.error(f"llama.cpp server did not start: {exc}")
            supervisor._notify(f"llama.cpp server did not start: {exc}")

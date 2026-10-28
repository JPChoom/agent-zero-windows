"""Keep the local model server (llama.cpp) in line with its settings.

The job loop runs about once a minute:
- With "Start with Agent Zero" on, the server is started once per Agent
  Zero start. A server that failed (for example it kept crashing) is not
  retried here; the user restarts it after fixing the cause. Crash recovery
  while running is the supervisor's own job.
- A running server whose saved settings changed (another model, preset,
  context size...) is restarted with the new ones, but only while no
  agent turn is running at all (a turn spends most of its time between model
  calls, in tools), so a turn is never cut off.
"""

import asyncio

from helpers import llama_server, local_server, model_concurrency
from helpers.extension import Extension
from helpers.print_style import PrintStyle

_tried = {"done": False}


def _turn_active() -> bool:
    """Is any chat in the middle of a turn, or a model call waiting or running?

    A turn alternates model calls with tools, terminals and file edits; between
    two model calls no call is waiting, so the model-call check alone lets a
    restart land mid-turn (the model is gone for a few seconds and the next
    call fails). Chat contexts report whether their task is alive.
    """
    if model_concurrency.foreground_busy():
        return True
    try:
        from agent import AgentContext

        return any(context.is_running() for context in AgentContext.all())
    except Exception:
        return True  # cannot tell: do not restart now

class LlamaServerAutostart(Extension):
    async def execute(self, **kwargs):
        sup = llama_server.get()
        state = sup.status()["state"]
        try:
            config = local_server.server_config()
        except llama_server.SupervisorError:
            return
        if state == "running":
            await self._apply_changes(sup, config)
            return
        if _tried["done"] or not local_server.settings().get("autostart"):
            return
        _tried["done"] = True  # once per Agent Zero start
        if state == "starting":
            return
        try:
            await asyncio.to_thread(sup.start, config)
            PrintStyle.success(f"llama.cpp server running at {sup.status()['api_base']}")
        except llama_server.SupervisorError as exc:
            PrintStyle.error(f"llama.cpp server did not start: {exc}")
            llama_server._notify(f"llama.cpp server did not start: {exc}")

    async def _apply_changes(self, sup, config) -> None:
        running = sup.running_identity()
        if not running or running == config.identity() or _turn_active():
            return
        PrintStyle.standard("llama.cpp server settings changed - restarting it with the new ones.")
        try:
            await asyncio.to_thread(sup.stop)
            await asyncio.to_thread(sup.start, config)
        except llama_server.SupervisorError as exc:
            PrintStyle.error(f"llama.cpp server did not restart: {exc}")
            llama_server._notify(f"llama.cpp server did not restart with the new settings: {exc}")

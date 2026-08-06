"""Test WhatsApp bridge connection health."""

from helpers.api import ApiHandler, Request
from helpers.errors import format_error
from helpers import plugins


PLUGIN_NAME = "_whatsapp_integration"


class TestConnection(ApiHandler):

    async def process(self, input: dict, request: Request) -> dict:
        config = input.get("config") or plugins.get_plugin_config(PLUGIN_NAME) or {}
        port = int(config.get("bridge_port", 3100))
        results: list[dict] = []

        await self._test_bridge(port, results)

        ok = all(r["ok"] for r in results)
        return {"success": ok, "results": results}

    async def _test_bridge(self, port: int, results: list[dict]) -> None:
        from plugins._whatsapp_integration.helpers.wa_client import get_health
        from plugins._whatsapp_integration.helpers.bridge_manager import get_bridge_url

        try:
            health = await get_health(get_bridge_url(port))
            status = health.get("status", "unknown")
            queue = health.get("queueLength", 0)
            uptime = health.get("uptime", 0)

            if status == "connected":
                results.append({
                    "test": "WhatsApp bridge",
                    "ok": True,
                    "message": f"Connected and ready (uptime: {uptime:.0f}s, queue: {queue})",
                })
            else:
                results.append({
                    "test": "WhatsApp bridge",
                    "ok": False,
                    "message": f"The bridge is running, but WhatsApp is not fully connected yet (status: {status}).",
                })
        except Exception as e:
            results.append({
                "test": "WhatsApp bridge",
                "ok": False,
                "message": f"Could not reach the local WhatsApp bridge: {format_error(e)}",
            })

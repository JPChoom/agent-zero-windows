from helpers.api import ApiHandler, Request
from helpers.errors import format_error
from plugins._autostart.helpers import startup


class Autostart(ApiHandler):
    """Start-at-logon status and switch. Only reachable from the signed-in,
    CSRF-checked WebUI: the agent's own commands that touch Run keys are
    refused by _safety_policy's persistence category."""

    async def process(self, input: dict, request: Request) -> dict:
        action = str(input.get("action") or "status").lower()
        try:
            if action == "enable":
                state = startup.enable()
            elif action == "disable":
                state = startup.disable()
            elif action == "status":
                state = startup.status()
            else:
                return {"success": False, "error": f"unknown action {action!r}"}
        except Exception as e:
            return {"success": False, "error": format_error(e), "status": startup.status()}
        return {"success": True, "status": state}

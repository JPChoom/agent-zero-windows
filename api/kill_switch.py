from helpers.api import ApiHandler, Request, Response
from helpers import kill_switch


class KillSwitch(ApiHandler):
    """Trip/reset/query the global kill switch (helpers/kill_switch.py) -
    backend for the always-visible header icon, not a chat/tool action.
    requires_auth defaults True (ApiHandler's own default) so this is
    gated the same as every other authenticated API endpoint; there is
    deliberately no tool that reaches this module, so the model itself
    has no path to call it.
    """

    async def process(self, input: dict, request: Request) -> dict | Response:
        action = str(input.get("action", "status") or "status").strip().lower()

        if action == "trip":
            kill_switch.trip(str(input.get("reason", "") or ""))
        elif action == "reset":
            kill_switch.reset()
        elif action != "status":
            return Response(response=f"Unknown action: {action}", status=400, mimetype="text/plain")

        return {"tripped": kill_switch.is_tripped(), "reason": kill_switch.get_reason()}

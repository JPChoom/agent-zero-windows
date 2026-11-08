from helpers.api import ApiHandler, Request
from plugins._capabilities.helpers import policy


class Known(ApiHandler):
    """Tool names and actions for the Capabilities settings: no chat data."""

    async def process(self, input: dict, request: Request) -> dict:
        return {"ok": True, "tools": policy.known_capabilities()}

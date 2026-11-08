from helpers.api import ApiHandler, Request
from plugins._model_config.helpers import job_routing


class RoutingStatus(ApiHandler):
    """Server states and recent fallbacks for Settings: no chat data."""

    async def process(self, input: dict, request: Request) -> dict:
        return {"ok": True, "servers": job_routing.server_states(),
                "fallbacks": list(job_routing.HISTORY)[-20:][::-1]}

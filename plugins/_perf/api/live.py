from helpers import perf
from helpers.api import ApiHandler, Request


class Live(ApiHandler):
    """Numbers for the sidebar speed counter: no chat text."""

    async def process(self, input: dict, request: Request) -> dict:
        return perf.live_state()

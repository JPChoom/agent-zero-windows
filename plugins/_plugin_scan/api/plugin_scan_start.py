from helpers.api import ApiHandler, Input, Output, Request
from helpers.plugin_review import start_queued_agent


class PluginScanStart(ApiHandler):
    """Start the agent on a context whose user message was already logged by the queue API."""

    async def process(self, input: Input, request: Request) -> Output:
        return start_queued_agent(input.get("context", ""), input.get("text", ""))

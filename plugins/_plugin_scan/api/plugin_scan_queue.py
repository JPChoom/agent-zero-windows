from helpers.api import ApiHandler, Input, Output, Request
from helpers.plugin_review import queue_prompt_message


class PluginScanQueue(ApiHandler):
    """Log the scan prompt into a chat before the scan starts."""

    async def process(self, input: Input, request: Request) -> Output:
        return queue_prompt_message(input.get("context", ""), input.get("text", ""))

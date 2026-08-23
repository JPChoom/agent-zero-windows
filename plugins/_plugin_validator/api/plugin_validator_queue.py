from helpers.api import ApiHandler, Input, Output, Request
from helpers.plugin_review import queue_prompt_message


class PluginValidatorQueue(ApiHandler):
    """Log the validation prompt into a chat. Optionally set progress to 'Queued'."""

    async def process(self, input: Input, request: Request) -> Output:
        queued_message = (
            "icon://hourglass_empty Queued - waiting for another validation to finish"
            if input.get("queued", False)
            else None
        )
        return queue_prompt_message(
            input.get("context", ""), input.get("text", ""), queued_message=queued_message
        )

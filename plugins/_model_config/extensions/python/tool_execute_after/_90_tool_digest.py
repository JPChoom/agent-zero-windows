"""Shorten a very long tool result, when turned on (helpers/tool_digest.py).

After the secret mask and the coding completion gate, which read the full
result, and before it reaches the history.
"""

from helpers.extension import Extension
from plugins._model_config.helpers import tool_digest


class ToolDigest(Extension):
    async def execute(self, response=None, tool_name: str = "", **kwargs):
        if not self.agent or response is None or not isinstance(getattr(response, "message", None), str):
            return
        response.message = await tool_digest.shorten(self.agent, tool_name, response.message)

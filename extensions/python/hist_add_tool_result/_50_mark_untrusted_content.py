from typing import Any

from helpers import untrusted_content
from helpers.extension import Extension


class MarkUntrustedContent(Extension):
    """Wrap external tool results as data and taint the chat.

    Runs before _90_save_tool_call_file so the saved copy carries the same
    marker the model sees. See helpers/untrusted_content.py.
    """

    def execute(self, data: dict[str, Any] | None = None, **kwargs):
        if not self.agent or not isinstance(data, dict):
            return
        tool_name = str(data.get("tool_name") or "")
        if untrusted_content.is_trusted_tool(tool_name):
            return
        result = data.get("tool_result")
        if not isinstance(result, str) or not result.strip():
            return
        if not untrusted_content.is_wrapped(result):
            data["tool_result"] = untrusted_content.wrap_tool_result(tool_name, result)
        untrusted_content.mark_tainted(self.agent)

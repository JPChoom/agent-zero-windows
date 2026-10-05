from __future__ import annotations

from helpers.tool import Response, Tool
from plugins.terminal_access.helpers.safe_executor import execute_command


class TerminalAccessTool(Tool):
    async def execute(self, command: str = "", shell: str = "powershell", **kwargs) -> Response:
        result = execute_command(command, shell)
        if result.get("status") == "success":
            message = result.get("output") or "Command completed with no output."
        else:
            message = f"Terminal command rejected or failed: {result.get('error', 'unknown error')}"
        return Response(message=message, break_loop=False, additional={"terminal": result})

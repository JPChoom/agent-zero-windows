from __future__ import annotations

from helpers.api import ApiHandler, Request, Response
from plugins.terminal_access.helpers.safe_executor import execute_command


class ExecuteCommandHandler(ApiHandler):
    @classmethod
    def requires_auth(cls) -> bool:
        return True

    @classmethod
    def requires_csrf(cls) -> bool:
        return True

    async def process(self, input: dict, request: Request) -> dict | Response:
        command = str(input.get("command", ""))
        shell = str(input.get("shell", "powershell"))
        return execute_command(command, shell)

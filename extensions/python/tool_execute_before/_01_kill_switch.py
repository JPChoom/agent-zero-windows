"""While the kill switch is tripped, refuse every tool that acts.

Before this, only a few tools checked the switch themselves (terminal,
Computer Use, desktop control, the Windows tools), so the browser, file
edits, MCP tools and remote execution kept working although the UI said
"all code execution halted" (enforcement audit finding E3, 2026-10-11).

Core, not plugin: disabling a plugin must not disable the kill switch. The
in-tool checks stay as a second layer. Named _01_ so it refuses before any
other gate spends effort (or an LLM call) on the call.

Still allowed while tripped: read-only tools (the permission rules'
classification), `response` (so the agent can say it is halted) and reading
or resetting a terminal's output.
"""

from helpers import kill_switch
from helpers.errors import RepairableException
from helpers.extension import Extension

_ALWAYS_ALLOWED = {"response"}
_TERMINAL_TOOLS = {"code_execution_tool", "code_execution_remote"}
_HARMLESS_RUNTIMES = {"output", "reset"}


def _is_read_only(tool_name: str, tool_args: dict) -> bool:
    if tool_name in _ALWAYS_ALLOWED:
        return True
    if tool_name in _TERMINAL_TOOLS:
        return str(tool_args.get("runtime", "")).strip().lower() in _HARMLESS_RUNTIMES
    try:
        from plugins._permissions.helpers import rules
    except Exception:
        return False  # cannot classify: treat as acting
    return rules.classify(tool_name, tool_args) == "read"


class KillSwitchGate(Extension):
    FAIL_LOUD = True  # its refusal is a raised exception; isolating it would let the tool run

    async def execute(self, tool_name: str = "", tool_args: dict | None = None, **kwargs) -> None:
        if not tool_name or not kill_switch.is_tripped():
            return
        if _is_read_only(tool_name, tool_args or {}):
            return
        raise RepairableException(
            kill_switch.denial_message()
            + " Only read-only tools work until then; tell the user instead of retrying."
        )

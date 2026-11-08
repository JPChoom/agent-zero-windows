"""After the agent writes or patches a file, report a syntax error in the same
tool result (helpers/quick_check.py). Before the completion gate (_80)."""

from helpers.extension import Extension, best_effort
from plugins._coding_controller.helpers import quick_check
from plugins._coding_controller.helpers.config import get_config

WRITING_ACTIONS = {"write", "patch"}


class QuickCheckAfterEdit(Extension):
    @best_effort("Quick syntax check after an edit")
    async def execute(self, response=None, tool_name: str = "", **kwargs):
        if not self.agent or response is None or not isinstance(getattr(response, "message", None), str):
            return
        name, _, method = str(tool_name or "").partition(":")
        if name != "text_editor":
            return
        tool = getattr(getattr(self.agent, "loop_data", None), "current_tool", None)
        args = getattr(tool, "args", None) or {}
        action = str(method or args.get("action") or "").strip().lower()
        if action not in WRITING_ACTIONS or not get_config(self.agent)["quick_check"]:
            return
        path = quick_check.resolve(args.get("path", ""))
        problem = quick_check.check(path) if path else ""
        if problem:
            response.message += (f"\n\nSyntax check: {args.get('path')} no longer parses ({problem}). "
                                 "Fix it before going on.")

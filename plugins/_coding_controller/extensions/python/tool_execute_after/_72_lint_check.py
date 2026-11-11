"""After the agent writes or patches a Python file, report the lint problems
the edit added (helpers/lint_check.py), after the syntax check (_70)."""

from helpers.extension import Extension, best_effort
from plugins._coding_controller.helpers import lint_check, quick_check
from plugins._coding_controller.helpers.config import get_config


class LintCheckAfterEdit(Extension):
    @best_effort("Lint check after an edit")
    async def execute(self, response=None, tool_name: str = "", **kwargs):
        if not self.agent or response is None or not isinstance(getattr(response, "message", None), str):
            return
        name, _, method = str(tool_name or "").partition(":")
        if name != "text_editor":
            return
        tool = getattr(getattr(self.agent, "loop_data", None), "current_tool", None)
        args = getattr(tool, "args", None) or {}
        action = str(method or args.get("action") or "").strip().lower()
        if action not in lint_check.WRITING_ACTIONS or not get_config(self.agent)["lint_check"]:
            return
        path = quick_check.resolve(args.get("path", ""))
        if not path or not lint_check.supports(path) or "no longer parses" in response.message:
            return
        after = lint_check.run(path)
        if after is None:
            return
        before = self.agent.loop_data.params_temporary.get(lint_check.BEFORE_KEY, {}).pop(path, [])
        response.message += lint_check.report(str(args.get("path")), lint_check.new_problems(before, after))

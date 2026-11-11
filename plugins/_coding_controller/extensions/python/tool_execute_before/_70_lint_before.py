"""Remember a Python file's lint problems before the agent edits it, so the
check after the edit can report only what the edit added
(helpers/lint_check.py)."""

from helpers.extension import Extension, best_effort
from plugins._coding_controller.helpers import lint_check, quick_check
from plugins._coding_controller.helpers.config import get_config


class LintBeforeEdit(Extension):
    @best_effort("Lint snapshot before an edit")
    async def execute(self, tool_name: str = "", tool_args: dict | None = None, **kwargs):
        if not self.agent:
            return
        name, _, method = str(tool_name or "").partition(":")
        args = tool_args or {}
        action = str(method or args.get("action") or "").strip().lower()
        if name != "text_editor" or action not in lint_check.WRITING_ACTIONS:
            return
        if not get_config(self.agent)["lint_check"] or not lint_check.ruff_path():
            return
        path = quick_check.resolve(args.get("path", ""))
        if not path or not lint_check.supports(path):
            return
        before = lint_check.run(path)  # None for a file that does not exist yet
        self.agent.loop_data.params_temporary.setdefault(lint_check.BEFORE_KEY, {})[path] = before or []

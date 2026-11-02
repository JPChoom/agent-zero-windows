from helpers.extension import Extension, best_effort
from plugins._skills.helpers import task_watch


class SkillTaskStep(Extension):
    """Count a finished tool step for the current task, note outside sources
    it read and learned skills it loaded, and whether the task was answered."""

    @best_effort("Track task step for skill learning")
    async def execute(self, tool_name: str = "", response=None, **kwargs):
        if not self.agent:
            return
        tool = getattr(getattr(self.agent, "loop_data", None), "current_tool", None)
        args = getattr(tool, "args", None) or {}
        try:
            from helpers.mcp_handler import MCPTool

            mcp = isinstance(tool, MCPTool)
        except Exception:
            mcp = False
        task_watch.on_tool(self.agent, tool_name, args, mcp=mcp)
        if self.agent.number == 0 and tool_name == "response" and getattr(response, "break_loop", False):
            task = task_watch.current(self.agent)
            if task is not None:
                task["answered"] = True

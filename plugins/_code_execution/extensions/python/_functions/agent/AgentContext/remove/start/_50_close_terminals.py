from helpers.extension import Extension
from plugins._code_execution.helpers import workspace_provider


class CloseTerminalsOnRemove(Extension):
    """The chat (or a parallel worker's context) is being deleted: end its
    terminal shells now instead of whenever garbage collection runs."""

    def execute(self, data: dict = {}, **kwargs):
        from agent import AgentContext

        args = data.get("args", ())
        context_id = args[0] if isinstance(args, tuple) and args else ""
        if context_id:
            workspace_provider.kill_context_terminals(AgentContext.get(str(context_id)))

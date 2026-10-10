from helpers.extension import Extension
from plugins._code_execution.helpers import workspace_provider


class CloseTerminalsOnReset(Extension):
    """The chat is being reset: its agents are replaced, so end their terminal
    shells now instead of whenever garbage collection runs."""

    def execute(self, data: dict = {}, **kwargs):
        args = data.get("args", ())
        context = args[0] if isinstance(args, tuple) and args else None
        workspace_provider.kill_context_terminals(context)

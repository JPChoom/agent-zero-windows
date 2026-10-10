from helpers import workspace
from helpers.extension import Extension


class WorkspaceReleaseOnRemove(Extension):
    """A chat or parallel worker context is ending: hand its apps to the chat
    that started it, or mark them orphaned (helpers/workspace.py)."""

    def execute(self, data: dict = {}, **kwargs):
        args = data.get("args", ())
        context_id = args[0] if isinstance(args, tuple) and args else ""
        if context_id:
            workspace.release_context(str(context_id))

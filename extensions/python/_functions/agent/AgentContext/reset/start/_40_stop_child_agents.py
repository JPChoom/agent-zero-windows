"""Stop a chat's child agents when the chat is reset (helpers/child_agents.py)."""

from helpers.extension import Extension


class StopChildAgents(Extension):
    def execute(self, data: dict = {}, **kwargs):
        try:
            from helpers import child_agents

            args = data.get("args", ())
            context = args[0] if isinstance(args, tuple) and args else None
            if context is not None and hasattr(context, "get_data"):
                child_agents.stop_all(context)
        except Exception:
            pass  # stopping children must never block the reset

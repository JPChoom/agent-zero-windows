"""Stop a chat's child agents when the chat is deleted (helpers/child_agents.py)."""

from helpers.extension import Extension


class StopChildAgents(Extension):
    def execute(self, data: dict = {}, **kwargs):
        try:
            from agent import AgentContext
            from helpers import child_agents

            args = data.get("args", ())
            context_id = args[0] if isinstance(args, tuple) and args else ""
            context = AgentContext.get(str(context_id)) if context_id else None
            if context is not None:
                child_agents.stop_all(context)
        except Exception:
            pass  # stopping children must never block deleting the parent

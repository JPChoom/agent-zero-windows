import time

from agent import AgentContext
from helpers import child_agents
from helpers.api import ApiHandler, Request


class Status(ApiHandler):
    """The child agents of a chat, live.

    input: {context_id, action?, name?}
      action "list" (default)  -> {ok, parent, current, now, children}
      action "stop" {name}     -> stops that child (its chat stays), then lists

    A chat that is itself a child lists its parent's children, so the panel
    shows its siblings and a way back to the parent.
    """

    async def process(self, input: dict, request: Request) -> dict:
        context = AgentContext.get(str(input.get("context_id") or ""))
        if context is None:
            return {"ok": True, "parent": None, "current": "", "now": time.time(), "children": []}
        parent_id = context.get_data(child_agents.CHILD_OF_KEY)
        parent = (AgentContext.get(str(parent_id)) if parent_id else None) or context
        error = ""
        if str(input.get("action") or "list") == "stop":
            try:
                child_agents.stop(parent, str(input.get("name") or ""))
            except child_agents.ChildAgentError as exc:
                error = str(exc)
        return {
            "ok": not error,
            "error": error,
            "parent": {"id": parent.id, "name": parent.name or parent.id},
            "current": context.id,
            "now": time.time(),
            "children": child_agents.describe(parent),
        }

import json

from helpers import child_agents
from helpers.errors import RepairableException
from helpers.tool import Response, Tool


class ChildAgent(Tool):
    """Named child agents in chats of their own (helpers/child_agents.py)."""

    async def execute(self, action: str = "", name: str = "", message: str = "", profile: str = "",
                      wait=True, timeout=None, repo: str = "", **kwargs):
        action = str(action or self.method or "start").strip().lower()
        wait = str(wait).strip().lower() not in ("false", "0", "no")
        try:
            limit = float(timeout) if timeout not in (None, "") else None
        except (TypeError, ValueError):
            limit = None
        try:
            if action in ("start", "message", "send"):
                if profile:
                    from tools.call_subordinate import _validate_subordinate_profile

                    profile = _validate_subordinate_profile(self.agent, profile)
                outcome = await child_agents.send(self.agent, name, message, profile=profile, wait=wait, timeout=limit,
                                                  repo=str(repo or "").strip())
            elif action in ("result", "wait"):
                outcome = await child_agents.result(self.agent, name, timeout=limit)
            elif action in ("status", "list"):
                outcome = {"children": child_agents.describe(self.agent.context)}
            elif action == "stop":
                outcome = child_agents.stop(self.agent.context, name)
            elif action == "forget":
                outcome = child_agents.forget(self.agent.context, name)
            else:
                raise child_agents.ChildAgentError("action must be start, message, result, status, stop or forget.")
        except child_agents.ChildAgentError as exc:
            raise RepairableException(str(exc)) from exc
        return Response(message=json.dumps(outcome, indent=2, ensure_ascii=False), break_loop=False)

    def get_log_object(self):
        return self.agent.context.log.log(
            type="subagent",
            heading=f"icon://communication {self.agent.agent_name}: Child agent",
            content="",
            kvps=self.args,
        )

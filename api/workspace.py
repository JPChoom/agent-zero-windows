from helpers import access_control, audit_log, kill_switch, workspace
from helpers.api import ApiHandler, Request, Response
from api.file_manager import caller


class WorkspaceApi(ApiHandler):
    """The Agent Workspace view: who owns which apps, terminals and browser tabs.

    actions:
      list                       -> {resources, contexts, control_enabled}
      adopt {id, context_id}     -> give a tracked app to a chat
      assign {id, agent}         -> move a tracked app to another agent (A0, A1, ...) of its chat
      release {id}               -> stop tracking an app (it is "the user's" again)
      close {id}                 -> end an app (needs Computer Use input enabled and
                                    the kill switch untripped, audited) or a terminal

    Apps are never closed automatically: they may hold unsaved work.
    """

    async def process(self, input: dict, request: Request) -> dict | Response:
        action = str(input.get("action") or "list")
        _, who = caller(request)
        rid = str(input.get("id") or "")

        if action == "list":
            return {"ok": True, **await self._state()}

        if action == "adopt":
            from agent import AgentContext

            context_id = str(input.get("context_id") or "")
            if not context_id or not AgentContext.get(context_id):
                return {"ok": False, "error": "Choose an open chat to give it to."}
            if not workspace.adopt(rid, context_id, by=who):
                return {"ok": False, "error": "That app is no longer running."}
            return {"ok": True, **await self._state()}

        if action == "assign":
            entry = next((r for r in workspace.apps() if r.id == rid), None)
            agent = str(input.get("agent") or "")
            if entry is None:
                return {"ok": False, "error": "That app is no longer running or no longer tracked."}
            if f"A{workspace.agent_number(agent)}" not in workspace.agent_names(entry.owner_context):
                return {"ok": False, "error": f"{agent or 'That agent'} is not an agent of the chat that owns this app."}
            workspace.assign(rid, entry.owner_context, agent, by=who)
            return {"ok": True, **await self._state()}

        if action == "release":
            if not workspace.release(rid, by=who):
                return {"ok": False, "error": "That item is not tracked any more."}
            return {"ok": True, **await self._state()}

        if action == "close":
            error = await self._close(rid, who)
            return {"ok": False, "error": error} if error else {"ok": True, **await self._state()}

        return {"ok": False, "error": f"Unknown action: {action}"}

    @staticmethod
    async def _state() -> dict:
        state = await workspace.snapshot()
        try:
            from plugins._computer_use.helpers import driver

            state["control_enabled"] = bool(driver.get_config(None)["control_enabled"])
        except Exception:
            state["control_enabled"] = False
        return state

    @staticmethod
    async def _close(rid: str, who: str) -> str:
        """Returns an error message, or "" when closed."""
        if rid.startswith("terminal:"):
            from plugins._code_execution.helpers import workspace_provider

            if not await workspace_provider.close_terminal(rid):
                return "That terminal is already closed."
            access_control.audit("workspace_close", by=who, resource=rid, kind="terminal")
            return ""

        resource = next((r for r in workspace.apps() if r.id == rid), None)
        if resource is None:
            return "That app is no longer running or no longer tracked."
        from plugins._computer_use.helpers import driver

        if not driver.get_config(None)["control_enabled"]:
            return "Computer Use input is disabled (Settings > Agent > Computer Use > Allow input)."
        if kill_switch.is_tripped():
            return kill_switch.denial_message()
        pid = resource.handle["pid"]
        await audit_log.append_record({
            "tool": "workspace", "action": "close", "pid": pid, "app": resource.label,
            "by": who, "context": resource.owner_context,
        })
        try:
            await driver.call(None, "kill_app", {"pid": int(pid), "session": "a0-workspace"})
        except driver.DriverError as exc:
            return f"Could not close it: {exc}"
        workspace.forget_app(pid)
        access_control.audit("workspace_close", by=who, resource=rid, kind="app", pid=pid, label=resource.label)
        return ""

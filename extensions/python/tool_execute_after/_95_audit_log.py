"""Writes a hash-chained audit record (helpers/audit_log.py) for
write-capable tool calls: text_editor (action=write/patch only, not
read), code_execution_tool (terminal/python/nodejs), and
call_subordinate.

Runs after _10_mask_secrets.py in this same directory (numeric ordering),
so response.message here is already secret-masked - the audit log never
gets a raw secret written into it.

Field coverage is honest about what's actually derivable at this hook
point rather than presenting placeholder data as real:
- policy_decision: not set here - plugins/_safety_policy/helpers/
  audit_log.py already records allow/deny decisions for commands it
  evaluates; duplicating that classification here would risk the two
  logs disagreeing. Left None; cross-reference the two logs if needed.
- exit_code: only code_execution_tool's terminal runtime has one, and
  even then the interactive/streaming terminal session doesn't surface
  it in a structured way at this hook point - left None rather than
  guessed from parsing response text.
- network_destinations: reserved for Phase I (advisory network-
  destination policy) to populate - left None/[] here.
"""

from helpers.extension import Extension
from helpers import audit_log

_STACK_KEY = "_audit_log_pending"
_WRITE_CAPABLE_TOOLS = {"text_editor", "code_execution_tool", "call_subordinate"}
_TEXT_EDITOR_WRITE_ACTIONS = {"write", "patch"}


class AuditLog(Extension):
    # Preserving pre-isolation behavior deliberately - see the paired
    # _95_audit_log_capture.py's FAIL_LOUD comment: whether a broken audit
    # trail should silently continue is a policy call, not mine to make.
    FAIL_LOUD = True

    async def execute(self, response=None, tool_name: str = "", **kwargs):
        if not self.agent:
            return

        stack = self.agent.data.get(_STACK_KEY)
        pending = stack.pop() if stack else None
        tool_args = (pending or {}).get("tool_args", {})

        if tool_name not in _WRITE_CAPABLE_TOOLS:
            return

        if tool_name == "text_editor":
            action = str(tool_args.get("action") or "").strip().lower()
            if action not in _TEXT_EDITOR_WRITE_ACTIONS:
                return
            program, arguments, working_directory, files_changed = (
                "text_editor",
                {"action": action, "path": tool_args.get("path")},
                None,
                [p for p in [tool_args.get("path")] if p],
            )
        elif tool_name == "code_execution_tool":
            program, arguments, working_directory, files_changed = (
                str(tool_args.get("runtime") or ""),
                {"code": tool_args.get("code")},
                tool_args.get("cwd") or None,
                [],
            )
        else:  # call_subordinate
            program, arguments, working_directory, files_changed = (
                "call_subordinate",
                {"profile": tool_args.get("profile"), "reset": tool_args.get("reset")},
                None,
                [],
            )

        task_id = None
        agent_role = None
        try:
            task_id = self.agent.context.id
        except Exception:
            pass
        try:
            agent_role = self.agent.config.profile
        except Exception:
            pass

        await audit_log.append_record({
            "task_id": task_id,
            "agent_role": agent_role,
            "tool": tool_name,
            "program": program,
            "arguments": arguments,
            "working_directory": working_directory,
            "policy_decision": None,
            "exit_code": None,
            "files_changed": files_changed,
            "network_destinations": None,
        })

"""Denies destructive/high-risk terminal commands before code_execution_tool
runs them.

Fires on tool_execute_before - the same, already-proven interception point
used by extensions/python/tool_execute_before/_20_block_parallel_recursion.py
and plugins/_infection_check's gate. Named _05_ so it runs before
_10_unmask_secrets.py (a deny decision never needs a real secret value) and
before _infection_check's _50_ LLM-based gate (an obviously-bad command
shouldn't cost an extra LLM call to also flag semantically).

Only code_execution_tool's "terminal" runtime is covered. "python"/"nodejs"
payloads can express the same dangerous intents in syntax these regexes
won't catch - see README.md.
"""

from helpers.extension import Extension
from helpers.errors import RepairableException
from plugins._safety_policy.helpers import audit_log, policy
from plugins._safety_policy.helpers.config import get_config


class SafetyCommandPolicy(Extension):

    async def execute(self, tool_name: str = "", tool_args: dict | None = None, **kwargs):
        if tool_name != "code_execution_tool" or not self.agent or not tool_args:
            return

        runtime = str(tool_args.get("runtime", "")).strip().lower()
        if runtime != "terminal":
            return

        cfg = get_config(self.agent)
        if not cfg["enforce_policy"]:
            return

        code = str(tool_args.get("code", ""))
        decision = policy.classify_command(code, cfg["custom_deny_patterns"])
        if decision.allowed:
            return

        context_id = str(getattr(getattr(self.agent, "context", None), "id", "") or "")
        audit_log.append_denial(
            {
                "context_id": context_id,
                "agent_name": getattr(self.agent, "agent_name", ""),
                "category": decision.category,
                "pattern": decision.pattern,
                "matched_text": decision.matched_text,
                "command": code,
            }
        )

        message = (
            f"[safety_policy] Denied: this terminal command matches the '{decision.category}' "
            f"deny category (matched '{decision.matched_text}'). This kind of operation is blocked "
            "regardless of intent - it is not something a normal coding task needs. If this was "
            "legitimate, the user can run it themselves, or add an exception in this plugin's settings."
        )
        try:
            self.agent.context.log.log(type="warning", content=message)
        except Exception:
            pass

        raise RepairableException(message)

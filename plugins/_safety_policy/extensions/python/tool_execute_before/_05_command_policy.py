"""Denies destructive/high-risk code_execution_tool calls before they run.

Fires on tool_execute_before - the same, already-proven interception point
used by extensions/python/tool_execute_before/_20_block_parallel_recursion.py
and plugins/_infection_check's gate. Named _05_ so it runs before
_10_unmask_secrets.py (a deny decision never needs a real secret value) and
before _infection_check's _50_ LLM-based gate (an obviously-bad command
shouldn't cost an extra LLM call to also flag semantically).

Covers all three code_execution_tool runtimes: "terminal" commands are
classified directly; "python"/"nodejs" source is scanned for the same
dangerous intents reached via a shell-out call (os.system, subprocess.*,
child_process.exec*/spawn*) - see policy.classify_source_code()'s docstring
for why that's scoped to shell-out call sites rather than the whole file,
and README.md for what's still not covered (native APIs like winreg/fs,
and any form of indirection).
"""

from helpers.extension import Extension
from helpers.errors import RepairableException
from plugins._safety_policy.helpers import audit_log, policy
from plugins._safety_policy.helpers.config import get_config

_SOURCE_RUNTIMES = {"python", "nodejs"}


class SafetyCommandPolicy(Extension):

    async def execute(self, tool_name: str = "", tool_args: dict | None = None, **kwargs):
        if tool_name != "code_execution_tool" or not self.agent or not tool_args:
            return

        runtime = str(tool_args.get("runtime", "")).strip().lower()
        if runtime != "terminal" and runtime not in _SOURCE_RUNTIMES:
            return

        cfg = get_config(self.agent)
        if not cfg["enforce_policy"]:
            return

        code = str(tool_args.get("code", ""))
        if runtime == "terminal":
            decision = policy.classify_command(code, cfg["custom_deny_patterns"])
        else:
            decision = policy.classify_source_code(code, cfg["custom_deny_patterns"])
        if decision.allowed:
            return

        context_id = str(getattr(getattr(self.agent, "context", None), "id", "") or "")
        audit_log.append_denial(
            {
                "context_id": context_id,
                "agent_name": getattr(self.agent, "agent_name", ""),
                "runtime": runtime,
                "category": decision.category,
                "pattern": decision.pattern,
                "matched_text": decision.matched_text,
                "command": code,
            }
        )

        subject = "terminal command" if runtime == "terminal" else f"{runtime} code"
        message = (
            f"[safety_policy] Denied: this {subject} matches the '{decision.category}' "
            f"deny category (matched '{decision.matched_text}'). This kind of operation is blocked "
            "regardless of intent - it is not something a normal coding task needs. If this was "
            "legitimate, the user can run it themselves, or add an exception in this plugin's settings."
        )
        try:
            self.agent.context.log.log(type="warning", content=message)
        except Exception:
            pass

        raise RepairableException(message)

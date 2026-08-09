"""Denies or holds-for-approval destructive/high-risk code_execution_tool
calls before they run.

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

A matched category is either hard-denied (raises immediately, same as
before) or approve-tier (per plugin config - see policy.py's
_APPROVAL_TIER_DEFAULT_CATEGORIES for the default split): the tool call is
held here, a safety_policy_approval_request message is logged for the UI
to render Approve/Deny buttons on, and this coroutine awaits the pending
decision (plugins/_safety_policy/helpers/approval_registry.py) up to
approval_timeout_seconds before treating an unanswered request as denied.
"""

import asyncio
import uuid

from helpers.extension import Extension
from helpers.errors import RepairableException
from helpers import kill_switch
from plugins._safety_policy.helpers import approval_registry, audit_log, policy
from plugins._safety_policy.helpers.config import get_config

_SOURCE_RUNTIMES = {"python", "nodejs"}


def _format_network_destination_note(decision) -> str:
    if not decision.network_destination:
        return ""
    known = "on the configured allowlist" if decision.network_destination_allowed else "not on the configured allowlist"
    return f" Destination host: {decision.network_destination} ({known})."


class SafetyCommandPolicy(Extension):

    async def execute(self, tool_name: str = "", tool_args: dict | None = None, **kwargs):
        if tool_name != "code_execution_tool" or not self.agent or not tool_args:
            return

        runtime = str(tool_args.get("runtime", "")).strip().lower()
        if runtime != "terminal" and runtime not in _SOURCE_RUNTIMES:
            return

        # Defense-in-depth check #1 (see code_execution_tool.py for #2):
        # checked here regardless of enforce_policy, so disabling this
        # plugin's own policy enforcement doesn't also disable the kill
        # switch - they are independent controls.
        if kill_switch.is_tripped():
            raise RepairableException(kill_switch.denial_message())

        cfg = get_config(self.agent)
        if not cfg["enforce_policy"]:
            return

        code = str(tool_args.get("code", ""))
        if runtime == "terminal":
            decision = policy.classify_command(
                code, cfg["custom_deny_patterns"], cfg["approval_tier_categories"],
                enable_network_allowlist=cfg["enable_network_destination_allowlist"],
                network_allowlist=cfg["network_destination_allowlist"],
            )
        else:
            decision = policy.classify_source_code(
                code, cfg["custom_deny_patterns"], cfg["approval_tier_categories"],
                enable_network_allowlist=cfg["enable_network_destination_allowlist"],
                network_allowlist=cfg["network_destination_allowlist"],
            )
        if decision.allowed:
            return

        context_id = str(getattr(getattr(self.agent, "context", None), "id", "") or "")
        agent_name = getattr(self.agent, "agent_name", "")
        subject = "terminal command" if runtime == "terminal" else f"{runtime} code"

        if decision.tier == "approve":
            await self._handle_approval(
                decision=decision,
                code=code,
                runtime=runtime,
                subject=subject,
                context_id=context_id,
                agent_name=agent_name,
                timeout=cfg["approval_timeout_seconds"],
            )
            return

        audit_log.append_denial(
            {
                "context_id": context_id,
                "agent_name": agent_name,
                "runtime": runtime,
                "category": decision.category,
                "pattern": decision.pattern,
                "matched_text": decision.matched_text,
                "command": code,
                "outcome": "denied",
                "network_destination": decision.network_destination,
                "network_destination_allowed": decision.network_destination_allowed,
            }
        )

        message = (
            f"[safety_policy] Denied: this {subject} matches the '{decision.category}' "
            f"deny category (matched '{decision.matched_text}'). This kind of operation is blocked "
            "regardless of intent - it is not something a normal coding task needs. If this was "
            "legitimate, the user can run it themselves, or add an exception in this plugin's settings."
            f"{_format_network_destination_note(decision)}"
        )
        self._log_warning(message)
        raise RepairableException(message)

    async def _handle_approval(
        self, *, decision, code, runtime, subject, context_id, agent_name, timeout
    ) -> None:
        approval_id = str(uuid.uuid4())
        audit_log.append_denial(
            {
                "context_id": context_id,
                "agent_name": agent_name,
                "runtime": runtime,
                "category": decision.category,
                "pattern": decision.pattern,
                "matched_text": decision.matched_text,
                "command": code,
                "outcome": "pending_approval",
                "approval_id": approval_id,
                "network_destination": decision.network_destination,
                "network_destination_allowed": decision.network_destination_allowed,
            }
        )

        message = (
            f"[safety_policy] Approval required: this {subject} matches the '{decision.category}' "
            f"category (matched '{decision.matched_text}'). Waiting up to {timeout}s for the user "
            "to Approve or Deny."
            f"{_format_network_destination_note(decision)}"
        )
        log_item = None
        try:
            log_item = self.agent.context.log.log(
                type="safety_policy_approval_request",
                content=message,
                kvps={
                    "approval_id": approval_id,
                    "category": decision.category,
                    "matched_text": decision.matched_text,
                    "command": code,
                    "runtime": runtime,
                    "resolved": False,
                    "network_destination": decision.network_destination,
                },
            )
        except Exception:
            pass

        future = approval_registry.register(approval_id)
        try:
            approved = await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            approval_registry.cleanup(approval_id)
            self._finish_approval(log_item, approval_id, approved=False, outcome="timeout")
            raise RepairableException(
                f"[safety_policy] Denied: no Approve/Deny response for this {subject} "
                f"within {timeout}s - treated as denied."
            )

        if not approved:
            self._finish_approval(log_item, approval_id, approved=False, outcome="denied")
            raise RepairableException(
                f"[safety_policy] Denied: the user denied this {subject} "
                f"(matched '{decision.category}')."
            )

        self._finish_approval(log_item, approval_id, approved=True, outcome="approved")

    def _finish_approval(self, log_item, approval_id: str, *, approved: bool, outcome: str) -> None:
        audit_log.append_denial(
            {"approval_id": approval_id, "outcome": outcome, "approved": approved}
        )
        if log_item is None:
            return
        try:
            # LogItem.update()'s `kvps=` parameter REPLACES the whole dict;
            # passing resolved/outcome as **kwargs instead merges them into
            # the existing kvps (see helpers/log.py's _update_item) so the
            # original approval_id/category/matched_text/command/runtime
            # the frontend needs stay intact.
            log_item.update(resolved=True, outcome=outcome)
        except Exception:
            pass

    def _log_warning(self, message: str) -> None:
        try:
            self.agent.context.log.log(type="warning", content=message)
        except Exception:
            pass

"""Gates every tool call on the configured permission mode and rules.

Runs on tool_execute_before, which already receives tool_name and
tool_args for *every* tool - _safety_policy uses the same hook but scopes
itself to code_execution_tool by early-returning.

Named _06_ so it runs *after* _safety_policy's _05_. That ordering is the
point: the safety policy is a floor for operations that are dangerous
regardless of intent (credential access, disk wipes, persistence), and it
must get its veto before any permission mode is consulted. Otherwise
"bypass" - a workflow preference - would silently disable a safety
control, which is not what "accepts all permissions" means in Claude
Code either, where prohibited actions stay prohibited in every mode.

An "ask" verdict reuses the approval-future registry that _safety_policy
already ships. That module is a plain future map with no dependency on
its plugin being enabled, so importing it is safe; the Approve/Deny UI is
this plugin's own, keyed on its own message type.
"""

import asyncio
import uuid

from helpers.errors import RepairableException
from helpers.extension import Extension
from helpers.print_style import PrintStyle
from plugins._permissions.helpers import rules
from plugins._permissions.helpers.config import get_config
from plugins._safety_policy.helpers import approval_registry


class PermissionGate(Extension):

    async def execute(self, tool_name: str = "", tool_args: dict | None = None, **kwargs):
        if not tool_name or not self.agent:
            return

        # The response tool ends a turn and writes nothing; gating it would
        # make the agent unable to reply that it needs permission, which is
        # a deadlock rather than a safeguard.
        if tool_name in ("response", "call_subordinate"):
            return

        try:
            cfg = get_config(self.agent)
        except Exception:
            # A broken config must not wedge every tool call. Failing open
            # here matches the pre-plugin behaviour rather than inventing a
            # lockout the user cannot undo from inside the UI.
            return

        verdict = rules.decide(
            tool_name, tool_args or {}, cfg["mode"], cfg["ruleset"]
        )
        if verdict.decision == "allow":
            return

        if verdict.decision == "deny":
            self._audit(cfg, tool_name, tool_args, verdict, "denied")
            message = (
                f"[permissions] Refused: {tool_name} - {verdict.reason}. "
                "Tell the user what you wanted to do and why; do not retry "
                "the same call."
            )
            if cfg["mode"] == "plan":
                message = (
                    f"[permissions] Plan mode is on, so {tool_name} cannot make "
                    "changes yet. Describe what you would do instead, and the "
                    "user can switch modes to let you proceed."
                )
            PrintStyle(font_color="#FFA500", padding=False).print(message)
            raise RepairableException(message)

        await self._ask(cfg, tool_name, tool_args or {}, verdict)

    async def _ask(self, cfg, tool_name, tool_args, verdict) -> None:
        approval_id = str(uuid.uuid4())
        timeout = cfg["approval_timeout_seconds"]
        target = rules.target_text(tool_name, tool_args)
        self._audit(cfg, tool_name, tool_args, verdict, "pending")

        log_item = None
        try:
            log_item = self.agent.context.log.log(
                type="permissions_approval_request",
                content=(
                    f"[permissions] {tool_name} needs approval - {verdict.reason}. "
                    f"Waiting up to {timeout}s."
                ),
                kvps={
                    "approval_id": approval_id,
                    "tool_name": tool_name,
                    "target": target,
                    "reason": verdict.reason,
                    "mode": cfg["mode"],
                    # Offered by the UI as "always allow", so answering once
                    # can stop the same question recurring.
                    "suggested_rule": rules.rule_for(tool_name, tool_args),
                    "suggested_tool_rule": rules.rule_for(
                        tool_name, tool_args, scope="tool"
                    ),
                    "resolved": False,
                },
            )
        except Exception:
            pass

        future = approval_registry.register(approval_id)
        try:
            approved = await asyncio.wait_for(future, timeout=timeout)
        except (TimeoutError, asyncio.TimeoutError):
            approval_registry.cleanup(approval_id)
            self._resolve_log(log_item, approved=False, outcome="timeout")
            raise RepairableException(
                f"[permissions] Denied: no answer for {tool_name} within "
                f"{timeout}s, so it was treated as denied. Tell the user "
                "rather than retrying."
            )

        if not approved:
            self._resolve_log(log_item, approved=False, outcome="denied")
            raise RepairableException(
                f"[permissions] The user declined {tool_name}. Do not retry it; "
                "ask what they would prefer instead."
            )

        self._resolve_log(log_item, approved=True, outcome="approved")

    def _resolve_log(self, log_item, approved: bool, outcome: str) -> None:
        if not log_item:
            return
        try:
            log_item.update(
                kvps={**(log_item.kvps or {}), "resolved": True,
                      "approved": approved, "outcome": outcome}
            )
        except Exception:
            pass

    def _audit(self, cfg, tool_name, tool_args, verdict, outcome: str) -> None:
        if not cfg.get("audit_decisions"):
            return
        try:
            from plugins._safety_policy.helpers import audit_log

            audit_log.append_denial(
                {
                    "source": "permissions",
                    "context_id": str(
                        getattr(getattr(self.agent, "context", None), "id", "") or ""
                    ),
                    "agent_name": getattr(self.agent, "agent_name", ""),
                    "tool": tool_name,
                    "target": rules.target_text(tool_name, tool_args or {}),
                    "mode": cfg["mode"],
                    "decision": verdict.decision,
                    "reason": verdict.reason,
                    "outcome": outcome,
                }
            )
        except Exception:
            # Audit failure must never block the decision itself.
            pass

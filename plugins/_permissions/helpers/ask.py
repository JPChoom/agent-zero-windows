"""Ask the user to approve one tool call through the chat's Approve/Deny card.

Shared by the permission gate (`_06_permissions.py`) and by tools that need
an extra, tool-specific confirmation the mode alone cannot express - for
example `computer_use` acting on a window the agent did not open. The card
is the same `permissions_approval_request` log item, answered through
`api/permissions_respond.py`, so the UI needs nothing new.
"""

from __future__ import annotations

import asyncio
import uuid

from helpers.errors import RepairableException
from plugins._permissions.helpers import rules
from plugins._safety_policy.helpers import approval_registry


async def request_approval(
    agent,
    tool_name: str,
    tool_args: dict | None,
    reason: str,
    mode: str,
    timeout: int,
    offer_rules: bool = True,
) -> None:
    """Wait for the user's answer; return on approval, raise RepairableException otherwise."""
    tool_args = tool_args or {}
    approval_id = str(uuid.uuid4())
    log_item = None
    try:
        log_item = agent.context.log.log(
            type="permissions_approval_request",
            content=(
                f"[permissions] {tool_name} needs approval - {reason}. "
                f"Waiting up to {timeout}s."
            ),
            kvps={
                "approval_id": approval_id,
                "tool_name": tool_name,
                "target": rules.target_text(tool_name, tool_args),
                "reason": reason,
                "mode": mode,
                # Offered by the UI as "always allow". Left empty when an
                # allow rule could not express the condition being asked
                # about (it would silently stop a safety question).
                "suggested_rule": rules.rule_for(tool_name, tool_args) if offer_rules else "",
                "suggested_tool_rule": rules.rule_for(tool_name, tool_args, scope="tool") if offer_rules else "",
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
        _resolve(log_item, approved=False, outcome="timeout")
        raise RepairableException(
            f"[permissions] Denied: no answer for {tool_name} within "
            f"{timeout}s, so it was treated as denied. Tell the user "
            "rather than retrying."
        )

    if not approved:
        _resolve(log_item, approved=False, outcome="denied")
        raise RepairableException(
            f"[permissions] The user declined {tool_name}. Do not retry it; "
            "ask what they would prefer instead."
        )
    _resolve(log_item, approved=True, outcome="approved")


def _resolve(log_item, approved: bool, outcome: str) -> None:
    if not log_item:
        return
    try:
        log_item.update(
            kvps={**(log_item.kvps or {}), "resolved": True,
                  "approved": approved, "outcome": outcome}
        )
    except Exception:
        pass

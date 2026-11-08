"""Refuse a tool call outside the agent's capability policy (helpers/policy.py).

Before the safety floor (_05) and the permission gate (_06): a capability
limit holds in every permission mode, Bypass included.
"""

from helpers.errors import RepairableException
from helpers.extension import Extension
from plugins._capabilities.helpers import policy


class CapabilityGate(Extension):
    FAIL_LOUD = True  # a refusal is a raised exception; isolating it would let the tool run

    async def execute(self, tool_name: str = "", tool_args: dict | None = None, **kwargs):
        if not tool_name or not self.agent:
            return
        # the call itself and every call it bundles (browser multi, parallel)
        reason = policy.denial_for_call(self.agent, tool_name, tool_args)
        if reason:
            raise RepairableException(reason)

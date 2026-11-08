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
        reason = policy.denial(self.agent, policy.capability_id(tool_name, tool_args))
        if reason:
            raise RepairableException(reason)

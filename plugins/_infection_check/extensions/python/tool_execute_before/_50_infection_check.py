from helpers import untrusted_content
from helpers.extension import Extension
from plugins._infection_check.helpers.checker import get_checker, get_config


class InfectionAwaitCheck(Extension):
    async def execute(self, tool_name="", tool_args={}, **kwargs):
        if not self.agent:
            return

        # Side-effect-free local reads can't do harm on their own; checking
        # them only costs a model call (~70s on a local model).
        if untrusted_content.is_read_only_call(tool_name, tool_args):
            return

        # Nothing external has entered this chat yet, so nothing could have
        # injected instructions. Configurable: the check also polices
        # credential exfiltration a user asks for directly, which this skip
        # leaves to the safety policy's credential_access floor.
        if get_config(self.agent).get("only_after_untrusted_content", True) and not untrusted_content.is_tainted(self.agent):
            return

        await get_checker(self.agent).gate(
            self.agent, tool_name=tool_name, tool_args=tool_args
        )

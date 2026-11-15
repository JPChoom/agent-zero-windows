from helpers import untrusted_content
from helpers.extension import Extension
from plugins._infection_check.helpers.checker import get_checker, get_config
from plugins._safety_policy.helpers import denials


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
        # A chat where the safety policy refused something is checked from
        # then on regardless: the likeliest next step is a workaround
        # (rule H5), and it needs no untrusted content to happen.
        if (
            get_config(self.agent).get("only_after_untrusted_content", True)
            and not untrusted_content.is_tainted(self.agent)
            and not denials.recent(self.agent)
        ):
            return

        # A `vm` action against a verifiably isolated guest cannot reach the
        # host, so an injected instruction confined to it has nothing to
        # attack - skip the check there (the safety floor already does not
        # gate vm actions). On a VM that is not provably isolated the check
        # stays. Opt out with the exempt_isolated_vm config.
        if (
            tool_name == "vm"
            and get_config(self.agent).get("exempt_isolated_vm", True)
            and _vm_target_is_isolated(tool_args)
        ):
            return

        await get_checker(self.agent).gate(
            self.agent, tool_name=tool_name, tool_args=tool_args
        )


def _vm_target_is_isolated(tool_args) -> bool:
    """True only when the plugins/_vm target VM is verifiably isolated.
    Fails safe: any import/lookup error means not isolated, so the check
    runs."""
    try:
        from plugins._vm.helpers import vbox

        name = str((tool_args or {}).get("vm") or "").strip()
        if not name or not vbox.installed():
            return False
        isolated, _reasons = vbox.vm_is_isolated(vbox.resolve(name))
        return bool(isolated)
    except Exception:
        return False

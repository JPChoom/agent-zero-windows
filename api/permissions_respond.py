from helpers.api import ApiHandler, Request, Response
from plugins._permissions.helpers import config as perm_config
from plugins._permissions.helpers import rules
from plugins._safety_policy.helpers import approval_registry


class PermissionsRespond(ApiHandler):
    """Backend for the Approve / Deny / Always allow buttons on a
    permissions_approval_request message.

    Mirrors api/safety_policy_approve.py, with one addition: an optional
    `remember` rule, written to the allow list before the pending call is
    released. That is what makes "always allow" mean something - otherwise
    the same question returns on the next identical call.

    The rule is saved first and the decision resolved second. Resolving
    first would let the tool run and the turn continue while the write is
    still in flight, so a failure to persist would be invisible.
    """

    async def process(self, input: dict, request: Request) -> dict | Response:
        approval_id = str(input.get("approval_id", "") or "").strip()
        approved = bool(input.get("approved", False))
        remember = str(input.get("remember", "") or "").strip()

        remembered = ""
        error = ""
        if approved and remember:
            try:
                remembered = perm_config.add_rule("allow", remember)
            except rules.RuleError as exc:
                # Report it rather than silently approving without the rule:
                # the user would otherwise believe they had stopped being
                # asked when they had not.
                error = f"could not save rule: {exc}"
            except Exception as exc:
                error = f"could not save rule: {exc}"

        resolved = (
            approval_registry.resolve(approval_id, approved) if approval_id else False
        )

        return {
            "resolved": resolved,
            "approved": approved,
            "remembered": remembered,
            "error": error,
        }

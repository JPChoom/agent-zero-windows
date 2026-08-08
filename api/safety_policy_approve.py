from helpers.api import ApiHandler, Request, Response
from plugins._safety_policy.helpers import approval_registry


class SafetyPolicyApprove(ApiHandler):
    """Resolves a pending _safety_policy approve-tier decision - the
    backend side of the Approve/Deny buttons rendered for a
    safety_policy_approval_request chat message. Follows api/pause.py's
    shape: a thin handler around one registry mutation.
    """

    async def process(self, input: dict, request: Request) -> dict | Response:
        approval_id = str(input.get("approval_id", "") or "").strip()
        approved = bool(input.get("approved", False))

        resolved = approval_registry.resolve(approval_id, approved) if approval_id else False

        return {"resolved": resolved, "approved": approved}

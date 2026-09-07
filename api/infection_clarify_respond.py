from helpers.api import ApiHandler, Request, Response
from plugins._safety_policy.helpers import approval_registry


class InfectionClarifyRespond(ApiHandler):
    """Backend for the Allow / Block buttons on an infection-check
    clarification request.

    Mirrors api/safety_policy_approve.py and shares its registry - both
    are "a gated call is parked on a future until a human answers", and a
    second registry would only add a second thing to keep correct.

    A response for an unknown or already-answered id resolves nothing and
    says so, which is what makes a double click or a click after the wait
    timed out harmless rather than an error.
    """

    async def process(self, input: dict, request: Request) -> dict | Response:
        approval_id = str(input.get("approval_id", "") or "").strip()
        approved = bool(input.get("approved", False))

        if not approval_id:
            return {"ok": False, "resolved": False, "error": "approval_id required"}

        resolved = approval_registry.resolve(approval_id, approved)
        return {"ok": True, "resolved": resolved, "approved": approved}

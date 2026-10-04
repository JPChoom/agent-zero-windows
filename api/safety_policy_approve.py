from helpers.api import ApiHandler, Request, Response
from plugins._safety_policy.helpers import approval_registry
from plugins._safety_policy.helpers import config as safety_config


class SafetyPolicyApprove(ApiHandler):
    """Resolves a pending _safety_policy approve-tier decision - the
    backend side of the Allow once / Always allow / Deny buttons rendered
    for a safety_policy_approval_request chat message and popup. Follows
    api/pause.py's shape: a thin handler around one registry mutation.

    `remember: true` (only meaningful with `approved: true`) additionally
    adds the request's download host to the allowlist. The host is read
    from the registry's server-side metadata for that approval, never from
    the request body, so a client can only remember the host it was
    actually asked about. The host is saved before the decision is
    resolved, mirroring api/permissions_respond.py: resolving first would
    let the command run while a failed save went unnoticed.
    """

    async def process(self, input: dict, request: Request) -> dict | Response:
        approval_id = str(input.get("approval_id", "") or "").strip()
        approved = bool(input.get("approved", False))
        remember = bool(input.get("remember", False))

        remembered = ""
        error = ""
        if approval_id and approved and remember:
            host = str(approval_registry.get_meta(approval_id).get("remember_host") or "")
            if host:
                try:
                    remembered = safety_config.add_allowed_host(host)
                except Exception as exc:
                    error = f"could not save allowed host: {exc}"
            else:
                error = "this request has no download host to remember"

        resolved = approval_registry.resolve(approval_id, approved) if approval_id else False

        return {
            "resolved": resolved,
            "approved": approved,
            "remembered": remembered,
            "error": error,
        }

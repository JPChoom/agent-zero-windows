from helpers.api import ApiHandler, Request, Response
from plugins._permissions.helpers import config as perm_config
from plugins._permissions.helpers import rules


# Shown in the mode selector. Text mirrors Claude Code's own descriptions,
# since the whole point of this feature is to behave the same way.
MODE_LABELS = {
    "auto": ("Auto", "Agent Zero handles permission decisions"),
    "manual": ("Manual", "Always ask before making changes"),
    "accept_edits": ("Accept edits", "Automatically accept all file edits"),
    "plan": ("Plan", "Create a plan before making changes"),
    "bypass": ("Bypass permissions", "Accepts all permissions"),
}


class PermissionsMode(ApiHandler):
    """Read or set the current permission mode.

    GET-shaped call with no `mode` returns the current value plus the list
    for the selector, so the UI needs only this one endpoint.
    """

    async def process(self, input: dict, request: Request) -> dict | Response:
        requested = input.get("mode")

        if requested is not None:
            try:
                stored = perm_config.set_mode(str(requested))
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            except Exception as exc:
                return {"ok": False, "error": f"could not save mode: {exc}"}
            return {"ok": True, "mode": stored}

        current = perm_config.get_config().get("mode", rules.DEFAULT_MODE)
        return {
            "ok": True,
            "mode": current,
            "modes": [
                {"id": key, "label": MODE_LABELS[key][0],
                 "description": MODE_LABELS[key][1]}
                for key in rules.MODES
            ],
        }

from helpers.api import ApiHandler, Request, Response
from helpers import access_control
from plugins._permissions.helpers import bypass_lock


class PermissionsBypassPassword(ApiHandler):
    """Status / set / change the Bypass-mode password.

    `{}` -> {"ok", "is_set"}.
    `{"new_password", "current_password"?}` -> sets it; changing an existing
    password requires the current one. Login + CSRF required (defaults).
    """

    async def process(self, input: dict, request: Request) -> dict | Response:
        new_password = input.get("new_password")
        if new_password is None:
            return {"ok": True, "is_set": bypass_lock.is_set()}

        client = access_control.client_ip(
            getattr(request, "remote_addr", None), getattr(request, "headers", {}) or {}
        ) or "?"
        try:
            bypass_lock.set_password(str(new_password), input.get("current_password"))
        except bypass_lock.BypassPasswordError as exc:
            access_control.audit("bypass_password_change_failed", ip=client, reason=str(exc))
            return {"ok": False, "error": str(exc), "is_set": bypass_lock.is_set()}
        access_control.audit("bypass_password_changed", ip=client)
        return {"ok": True, "is_set": True}

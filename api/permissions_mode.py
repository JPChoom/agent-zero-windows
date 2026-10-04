from helpers.api import ApiHandler, Request, Response
from helpers import access_control
from plugins._permissions.helpers import bypass_lock, mode_state
from plugins._permissions.helpers import rules


# Shown in the mode selector. Text mirrors Claude Code's own descriptions,
# since the whole point of this feature is to behave the same way.
MODE_LABELS = {
    "auto": ("Auto", "Agent Zero handles permission decisions"),
    "manual": ("Manual", "Always ask before making changes"),
    "accept_edits": ("Accept edits", "Automatically accept all file edits"),
    "plan": ("Plan", "Create a plan before making changes"),
    "bypass": ("Bypass permissions", "Accepts all permissions (password required)"),
}

# Safest -> least safe, matching rules.MODES' order. Used by the selector to
# color-code each option so the safety gradient reads at a glance instead of
# just from the ordering.
MODE_COLORS = {
    "plan": "#22c55e",
    "manual": "#84cc16",
    "accept_edits": "#eab308",
    "auto": "#f97316",
    "bypass": "#ef4444",
}

# Shared with the login form's limiter class, separate counters.
bypass_throttle = access_control.LoginThrottle()


def _state_payload(state: dict) -> dict:
    return {
        "mode": state["mode"],
        "bypass_until": state.get("bypass_until", 0),
        "unlocked_at": state.get("unlocked_at", 0),
    }


class PermissionsMode(ApiHandler):
    """Read or set the permission mode of one chat (`ctxid`).

    Modes are per chat and in memory (plugins/_permissions/helpers/
    mode_state.py). Switching to "bypass" requires the Bypass password
    (`password`), which is separate from the login and rate-limited.
    """

    async def process(self, input: dict, request: Request) -> dict | Response:
        ctxid = str(input.get("ctxid") or "").strip()
        project = self._project(ctxid)
        requested = input.get("mode")

        if requested is not None:
            requested = str(requested).strip().lower()
            if not ctxid:
                return {"ok": False, "error": "Open a chat first - the mode applies to one chat."}

            if requested == "bypass":
                if not bypass_lock.is_set():
                    return {
                        "ok": False,
                        "error": "Set a Bypass password in Settings > Security first.",
                        "needs_setup": True,
                    }
                client = access_control.client_ip(
                    getattr(request, "remote_addr", None), getattr(request, "headers", {}) or {}
                ) or "?"
                if bypass_throttle.is_locked(client):
                    access_control.audit("bypass_locked", ip=client, ctxid=ctxid)
                    return {"ok": False, "error": "Too many wrong attempts. Try again later.", "needs_password": True}
                if not bypass_lock.verify(input.get("password")):
                    locked = bypass_throttle.record_failure(client)
                    access_control.audit("bypass_failure", ip=client, ctxid=ctxid, locked=locked)
                    return {"ok": False, "error": "Wrong Bypass password.", "needs_password": True}
                bypass_throttle.record_success(client)
                access_control.audit("bypass_unlocked", ip=client, ctxid=ctxid)

            try:
                state = mode_state.set_mode(ctxid, requested, project)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            except Exception as exc:
                return {"ok": False, "error": f"could not change mode: {exc}"}
            return {"ok": True, **_state_payload(state)}

        state = mode_state.get_mode(ctxid or None, project)
        return {
            "ok": True,
            **_state_payload(state),
            "default_mode": mode_state.default_mode(),
            "bypass_password_set": bypass_lock.is_set(),
            "modes": [
                {"id": key, "label": MODE_LABELS[key][0],
                 "description": MODE_LABELS[key][1],
                 "color": MODE_COLORS[key]}
                for key in rules.MODES
            ],
        }

    def _project(self, ctxid: str) -> str:
        if not ctxid:
            return ""
        try:
            from agent import AgentContext

            context = AgentContext.get(ctxid)
        except Exception:
            context = None
        return mode_state.context_project(context) if context is not None else ""

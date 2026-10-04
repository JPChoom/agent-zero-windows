from helpers.api import ApiHandler, Request, Response
from helpers import access_control
from helpers import settings as settings_helper
from plugins._permissions.helpers import bypass_lock


class SecuritySettings(ApiHandler):
    """Backend of Settings > Security: the tunnel IP allowlist and its
    blocked-attempt log. (Default permission mode and Bypass time limit are
    ordinary settings fields; the Bypass password has its own endpoint.)

    actions:
      get                                  -> current state
      save_allowlist {text, enabled, password?}
      allow_ip {ip}                        -> append one address

    Lockout guard: a change made remotely (through the tunnel) that would
    stop the requester's own address from getting in again requires the
    Bypass password - otherwise one typo locks the user out until they're
    back at this PC.
    """

    async def process(self, input: dict, request: Request) -> dict | Response:
        action = str(input.get("action") or "get")
        remote_addr = getattr(request, "remote_addr", None)
        headers = getattr(request, "headers", {}) or {}
        is_local = access_control.is_local_request(remote_addr, headers)
        my_ip = "" if is_local else access_control.client_ip(remote_addr, headers)

        if action == "get":
            return self._state(is_local, my_ip)

        if action == "allow_ip":
            ip = str(input.get("ip") or "").strip()
            if access_control.invalid_allowlist_entries(ip) or not ip:
                return {"ok": False, "error": f"Not a valid IP address: {ip!r}"}
            current = str(settings_helper.get_settings().get("tunnel_ip_allowlist", "") or "")
            if access_control.ip_in_allowlist(ip, access_control.parse_allowlist(current)):
                return {"ok": True, **self._state(is_local, my_ip)}
            text = (current.rstrip() + "\n" if current.strip() else "") + ip
            return self._save(text, True, is_local, my_ip, input.get("password"), event="allowlist_ip_added")

        if action == "save_allowlist":
            text = str(input.get("text") or "")
            enabled = bool(input.get("enabled", True))
            bad = access_control.invalid_allowlist_entries(text)
            if bad:
                return {"ok": False, "error": "Not valid IPs/ranges: " + ", ".join(bad)}
            return self._save(text, enabled, is_local, my_ip, input.get("password"), event="allowlist_saved")

        return {"ok": False, "error": f"Unknown action: {action}"}

    def _save(self, text, enabled, is_local, my_ip, password, event) -> dict:
        if not is_local and enabled:
            would_allow_me = access_control.ip_in_allowlist(my_ip, access_control.parse_allowlist(text))
            if not would_allow_me and not bypass_lock.verify(password):
                return {
                    "ok": False,
                    "needs_password": True,
                    "error": (
                        f"This change would block your current address ({my_ip or 'unknown'}). "
                        "Enter the Bypass password to confirm."
                    ),
                }
        settings_helper.set_settings_delta(
            {"tunnel_ip_allowlist": text.strip(), "tunnel_allowlist_enabled": enabled}
        )
        access_control.invalidate_policy_cache()
        access_control.audit(event, by=my_ip or "local", enabled=enabled)
        return {"ok": True, **self._state(is_local, my_ip)}

    def _state(self, is_local: bool, my_ip: str) -> dict:
        s = settings_helper.get_settings()
        text = str(s.get("tunnel_ip_allowlist", "") or "")
        return {
            "ok": True,
            "allowlist": text,
            "enabled": bool(s.get("tunnel_allowlist_enabled", True)),
            "invalid": access_control.invalid_allowlist_entries(text),
            "blocked": access_control.recent_blocks(),
            "is_local": is_local,
            "my_ip": my_ip,
            "bypass_password_set": bypass_lock.is_set(),
        }

import asyncio
import threading

from helpers import access_control, process, windows_update
from helpers.api import ApiHandler, Request, Response


class WindowsUpdate(ApiHandler):
    """Settings > Check for updates on a native Windows install.

    actions:
      check {force?}  -> release and readiness info (windows_update.check)
      apply {tag}     -> fast-forward to the release; restart required
      rollback        -> back to the commit before the last update; restart required
      restart         -> restart the server so updated code runs
    """

    async def process(self, input: dict, request: Request) -> dict | Response:
        action = str(input.get("action") or "check")
        remote_addr = getattr(request, "remote_addr", None)
        headers = getattr(request, "headers", {}) or {}
        who = "local" if access_control.is_local_request(remote_addr, headers) else access_control.client_ip(remote_addr, headers)

        if action == "check":
            return {"ok": True, **await windows_update.check(force=bool(input.get("force")))}

        if action in ("apply", "rollback"):
            tag = str(input.get("tag") or "")
            try:
                if action == "apply":
                    result = await asyncio.to_thread(windows_update.apply, tag)
                else:
                    result = await asyncio.to_thread(windows_update.rollback)
            except windows_update.UpdateError as exc:
                access_control.audit(f"update_{action}_failed", by=who, tag=tag, error=str(exc)[:500])
                return {"ok": False, "error": str(exc)}
            access_control.audit(f"update_{action}", by=who, **{k: v for k, v in result.items() if k != "ok"})
            return result

        if action == "restart":
            access_control.audit("update_restart", by=who)
            # A thread, not the request's event loop: that loop ends with the
            # response, so a callback scheduled on it never runs.
            threading.Timer(1.0, process.reload).start()
            return {"ok": True}

        return {"ok": False, "error": f"Unknown action: {action}"}

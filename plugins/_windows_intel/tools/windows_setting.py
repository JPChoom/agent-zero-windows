"""Agent-facing tool: list, read and change a few safe per-user Windows settings.

Only the settings in helpers/settings_catalog.py exist; each `set` is
validated against that setting's allowed values, kill-switch gated, written
to the audit log first, and reports the previous value so the change can be
undone. `list` and `get` are reads; `set` is an execute action for the
permission engine (asks in Manual, refused in Plan).
"""

from __future__ import annotations

import asyncio

from helpers import audit_log, kill_switch
from helpers.tool import Response, Tool
from plugins._windows_intel.helpers import settings_catalog as cat


class WindowsSetting(Tool):

    backend: cat.Backend | None = None  # tests inject a fake

    async def execute(self, action: str = "list", setting: str = "", value: str = "", **kwargs) -> Response:
        action = str(action or "list").strip().lower()
        if kwargs:
            return self._msg(f"windows_setting does not take {', '.join(map(repr, kwargs))}; use action, setting, value.")
        backend = self.backend or cat.Backend()
        try:
            if action == "list":
                return self._msg(await asyncio.to_thread(self._list, backend))
            spec = cat.CATALOG.get(str(setting or "").strip().lower())
            if not spec:
                return self._msg(f"windows_setting: unknown setting {setting!r}; available: {', '.join(cat.CATALOG)}.")
            unavailable = spec.available(backend)
            if unavailable:
                return self._msg(f"windows_setting: {spec.name} {unavailable}.")
            if action == "get":
                return self._msg(f"{spec.name}: {await asyncio.to_thread(spec.get, backend)}")
            if action != "set":
                return self._msg("windows_setting: action must be list, get or set.")
            if kill_switch.is_tripped():
                return self._msg(kill_switch.denial_message())
            target = cat.normalize_value(spec, value, backend)
            previous = await asyncio.to_thread(spec.get, backend)
            await audit_log.append_record({
                "tool": "windows_setting", "action": "set", "setting": spec.name,
                "from": previous, "to": target,
                "context": getattr(getattr(self.agent, "context", None), "id", ""),
            })
            await asyncio.to_thread(spec.set, backend, target)
            now = await asyncio.to_thread(spec.get, backend)
            return self._msg(
                f"{spec.name}: {previous} -> {now}. To undo: windows_setting action=set setting={spec.name} value={previous}"
            )
        except cat.SettingError as exc:
            return self._msg(f"windows_setting: {exc}")
        except Exception as exc:
            return self._msg(f"windows_setting {action} failed: {type(exc).__name__}: {exc}")

    def _msg(self, text: str) -> Response:
        return Response(message=text, break_loop=False)

    @staticmethod
    def _list(backend: cat.Backend) -> str:
        lines = ["setting | current | allowed values"]
        for spec in cat.CATALOG.values():
            unavailable = spec.available(backend)
            if unavailable:
                lines.append(f"{spec.name} | - | {unavailable}")
                continue
            try:
                current, choices = spec.get(backend), spec.choices(backend)
            except cat.SettingError as exc:
                current, choices = f"(error: {exc})", []
            lines.append(f"{spec.name} | {current} | {', '.join(choices)}")
        return "\n".join(lines)

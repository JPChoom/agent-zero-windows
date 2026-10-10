"""Agent-facing tool: operate Windows apps through their UI Automation tree.

Backed by trycua's cua-driver (helpers/driver.py). Input is delivered in
the background (UIA patterns / PostMessage) - the user's mouse does not
move and focus is not taken - unless the driver reports the target cannot
be driven that way and the call is repeated with delivery="foreground".

Gates, in order:
1. Read actions (apps, windows, inspect, screenshot, status) are always
   available; everything else needs `control_enabled` (default off).
2. Kill switch: refuses non-read actions while tripped.
3. Hard limits (helpers/policy.py): sign-in/elevation/password-manager
   windows, typing into terminals, lock/log-off key combos, secret fields.
   No mode lifts these.
4. The permission gate (_permissions) has already applied the chat's mode:
   plan refuses, manual asks. On top of that, outside bypass, this tool asks
   before input into a window the agent did not open itself in this chat
   (it could be the user's unsaved document), before foreground delivery
   (it takes focus and moves the real pointer) and before risky hotkeys.
5. Every non-read action is appended to the audit log before it runs.

Window contents are outside data: the result is wrapped as untrusted
content like any other non-A0 tool result.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path

from helpers import audit_log, files, kill_switch, workspace
from helpers.errors import RepairableException
from helpers.tool import Response, Tool
from plugins._computer_use.helpers import driver, policy

_LABELS_KEY = "_computer_use_element_labels"
_FOCUS_KEY = "_computer_use_last_field"


class ComputerUse(Tool):

    async def execute(self, action: str = "", **kwargs) -> Response:
        await self.agent.handle_intervention()
        action = str(action or "").strip().lower()
        handlers = {
            "status": self._status,
            "apps": self._apps,
            "windows": self._windows,
            "inspect": self._inspect,
            "screenshot": self._screenshot,
            "launch": self._launch,
            "click": self._click,
            "type": self._type,
            "set_value": self._set_value,
            "key": self._key,
            "hotkey": self._hotkey,
            "scroll": self._scroll,
            "menu": self._menu,
            "focus": self._focus,
            "close": self._close,
            "hand_over": self._hand_over,
            "stop_driver": self._stop_driver,
        }
        handler = handlers.get(action)
        if not handler:
            return self._msg(f"Unknown action {action!r}. Use one of: {', '.join(sorted(handlers))}.")

        cfg = driver.get_config(self.agent)
        if action not in policy.READ_ACTIONS and action != "stop_driver":
            if not cfg["control_enabled"]:
                return self._msg(
                    "Computer use input is disabled (Settings > Agent > Computer Use > "
                    "'Allow input'). Read actions (apps, windows, inspect, screenshot) still work. "
                    "Tell the user instead of retrying."
                )
            if kill_switch.is_tripped():
                return self._msg(kill_switch.denial_message())

        try:
            return await handler(cfg=cfg, **kwargs)
        except driver.DriverError as exc:
            return self._msg(f"computer_use: {exc}")
        except RepairableException:
            raise
        except Exception as exc:
            return self._msg(f"computer_use {action} failed: {exc}")

    # -- helpers ----------------------------------------------------------

    def _msg(self, text: str) -> Response:
        return Response(message=text, break_loop=False)

    def _session(self) -> str:
        return f"a0-{str(getattr(self.agent.context, 'id', '') or 'chat')[:12]}"

    def _data(self, key: str, default):
        data = self.agent.context.data
        if key not in data:
            data[key] = default
        return data[key]

    async def _call(self, tool: str, args: dict) -> dict:
        args = {k: v for k, v in args.items() if v is not None}
        args["session"] = self._session()
        return await driver.call(self.agent, tool, args)

    async def _process_name(self, pid) -> str:
        if pid in (None, ""):
            return ""
        try:
            data = await self._call("list_windows", {"pid": int(pid)})
            for w in data.get("windows") or []:
                if w.get("app_name"):
                    return str(w["app_name"])
            apps = await self._call("list_apps", {})
            for a in apps.get("apps") or []:
                if a.get("pid") == int(pid):
                    return str(a.get("name") or "")
        except Exception:
            return ""
        return ""

    def _context_id(self) -> str:
        return str(getattr(self.agent.context, "id", ""))

    def _owned(self, pid) -> bool:
        """Whether this agent owns the app: it (or a sub-agent under it, or a
        parallel job it started) launched it and that same process is still
        running. Apps of the agents above it are not its own. Ownership lives in
        helpers/workspace.py so it survives a worker's temporary context."""
        return workspace.owns_app(self._context_id(), pid, int(getattr(self.agent, "number", 0) or 0))

    async def _guard(self, action: str, pid, *, keys=None, element_label: str = "",
                     foreground: bool = False, args: dict | None = None) -> None:
        """Hard limits, extra approvals and the audit record for one input action."""
        proc = await self._process_name(pid)
        refused = policy.refusal(action, proc, keys=keys, element_label=element_label)
        if refused:
            raise RepairableException(f"[computer_use] Refused: {refused}")

        reasons = []
        if pid in (None, ""):
            reasons.append("it acts on the whole desktop rather than a window the agent opened")
        elif not self._owned(pid):
            entry = workspace.find_app(pid)
            if entry and entry.state == workspace.ACTIVE and entry.owner_context == self._context_id():
                reasons.append(f"{proc or 'pid ' + str(pid)} belongs to {entry.owner_agent or 'A0'}, an agent above this one in the chat")
            else:
                reasons.append(f"{proc or 'pid ' + str(pid)} was not opened by the agent in this chat, so it may hold the user's own work")
        if foreground:
            reasons.append("foreground delivery takes focus and moves the real pointer")
        if action == "hotkey" and policy.risky_hotkey(keys):
            reasons.append(f"{'+'.join(policy.normalize_keys(keys))} can close a window with unsaved work")

        if reasons:
            from plugins._permissions.helpers import rules
            from plugins._permissions.helpers.ask import request_approval
            from plugins._permissions.helpers.config import get_config as perm_config

            pcfg = perm_config(self.agent)
            call_args = {"action": action, "pid": pid, **(args or {})}
            # Bypass means "stop asking". If the permission gate already put
            # this call in front of the user (an "ask" verdict), a second
            # card would be noise; otherwise - auto mode, or an allow rule -
            # nobody has looked at it yet, so ask with the specific reason.
            gate_asked = rules.decide("computer_use", call_args, pcfg["mode"], pcfg["ruleset"]).decision == "ask"
            if pcfg["mode"] != "bypass" and not gate_asked:
                await request_approval(
                    self.agent, "computer_use", call_args,
                    "; ".join(reasons), pcfg["mode"], pcfg["approval_timeout_seconds"],
                    offer_rules=False,
                )

        await audit_log.append_record({
            "tool": "computer_use",
            "agent_role": getattr(self.agent, "agent_name", ""),
            "action": action,
            "pid": pid,
            "process": proc,
            "owned": self._owned(pid),
            "foreground": foreground,
            "arguments": {k: (v if k != "text" else f"<{len(str(v))} chars>") for k, v in (args or {}).items()},
            "context": getattr(self.agent.context, "id", ""),
        })

    @staticmethod
    def _delivery(kwargs) -> str | None:
        mode = str(kwargs.get("delivery") or kwargs.get("delivery_mode") or "").strip().lower()
        return "foreground" if mode == "foreground" else None

    @staticmethod
    def _summary(data: dict) -> str:
        if data.get("refusal"):
            r = data["refusal"]
            return f"Driver refused ({r.get('code')}): {r.get('message')}"
        parts = [str(data.get("summary") or "").strip()]
        esc = data.get("escalation") or {}
        if esc.get("target") == "foreground":
            parts.append(
                "Background delivery could not be confirmed for this window. If nothing changed, "
                "inspect again; only then repeat with delivery=\"foreground\" (asks the user first)."
            )
        if data.get("effect") == "unverifiable":
            parts.append("The effect is unverified: inspect the window to confirm.")
        text = "\n".join(p for p in parts if p)
        return text or "Done."

    def _save_png(self, b64: str, name: str) -> str:
        folder = Path(files.get_abs_path("tmp", "computer_use"))
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{name}-{int(time.time())}.png"
        path.write_bytes(base64.b64decode(b64))
        return str(path)

    # -- read actions -----------------------------------------------------

    async def _status(self, cfg, **kwargs) -> Response:
        try:
            exe = driver.find_executable(cfg)
        except driver.DriverError as exc:
            return self._msg(str(exc))
        running = driver.is_running(exe)
        return self._msg(
            f"cua-driver: {exe}\ndaemon running: {running}\ninput allowed: {cfg['control_enabled']}"
        )

    async def _apps(self, cfg, **kwargs) -> Response:
        data = await self._call("list_apps", {})
        rows = []
        for a in data.get("apps") or []:
            if not a.get("running"):
                continue
            rows.append(f"pid {a.get('pid')} | {a.get('name')} | windows: {len(a.get('windows') or [])}"
                        + (" | agent-opened" if self._owned(a.get("pid")) else ""))
        return self._msg("Running apps:\n" + ("\n".join(rows[:200]) or "(none)"))

    async def _windows(self, cfg, **kwargs) -> Response:
        data = await self._call("list_windows", {"pid": kwargs.get("pid"), "on_screen_only": kwargs.get("on_screen_only")})
        rows = []
        for w in data.get("windows") or []:
            rows.append(
                f"pid {w.get('pid')} | window_id {w.get('window_id')} | {w.get('app_name')} | "
                f"{w.get('title')!r}" + (" | minimized" if w.get("minimized") else "")
                + (" | agent-opened" if self._owned(w.get("pid")) else "")
            )
        return self._msg("Windows:\n" + ("\n".join(rows[:300]) or "(none)"))

    async def _inspect(self, cfg, pid=None, window_id=None, screenshot=False, **kwargs) -> Response:
        if pid in (None, ""):
            raise RepairableException("inspect needs `pid` (and usually `window_id`) - get them from action=windows.")
        proc = await self._process_name(pid)
        refused = policy.refusal("inspect", proc)
        if refused:
            raise RepairableException(f"[computer_use] Refused: {refused}")
        data = await self._call("get_window_state", {"pid": int(pid), "window_id": int(window_id) if window_id else None})
        if data.get("refusal"):
            return self._msg(self._summary(data))
        labels = self._data(_LABELS_KEY, {})
        lines = [f"Window {data.get('window_title')!r} ({data.get('app_name')}, pid {pid}, window_id {data.get('window_id')}):"]
        elements = data.get("elements") or []
        for e in elements[: cfg["max_elements"]]:
            token = e.get("element_token")
            label = str(e.get("label") or "")
            labels[token] = label
            value = str(e.get("value") or "")
            if policy.is_secret_label(label):
                value = "<hidden>" if value else ""
            value = (value[:120] + "...") if len(value) > 120 else value
            acts = ",".join(e.get("actions") or [])
            lines.append(
                f"{token} | {e.get('role')} | {label!r}"
                + (f" | value={value!r}" if value else "")
                + (f" | {acts}" if acts else "")
                + ("" if e.get("enabled", True) else " | disabled")
            )
        if len(elements) > cfg["max_elements"]:
            lines.append(f"... {len(elements) - cfg['max_elements']} more elements not shown.")
        if screenshot and data.get("screenshot_png_b64"):
            path = self._save_png(data["screenshot_png_b64"], f"window-{pid}")
            lines.append(f"Screenshot saved to {path} - load it with vision_load to look at it.")
        lines.append("Tokens are valid until the next inspect of this window.")
        return self._msg("\n".join(lines))

    async def _screenshot(self, cfg, pid=None, window_id=None, **kwargs) -> Response:
        if pid not in (None, ""):
            refused = policy.refusal("screenshot", await self._process_name(pid))
            if refused:
                raise RepairableException(f"[computer_use] Refused: {refused}")
            data = await self._call("get_window_state", {"pid": int(pid), "window_id": int(window_id) if window_id else None})
            b64, name = data.get("screenshot_png_b64"), f"window-{pid}"
        else:
            data = await self._call("get_desktop_state", {"max_image_dimension": 1920})
            b64, name = data.get("screenshot_png_b64"), "desktop"
        if not b64:
            return self._msg(self._summary(data) if data else "No screenshot returned.")
        return self._msg(f"Screenshot saved to {self._save_png(b64, name)} - load it with vision_load to look at it.")

    # -- input actions ----------------------------------------------------

    async def _launch(self, cfg, app="", **kwargs) -> Response:
        app = str(app or kwargs.get("name") or "").strip()
        if not app:
            raise RepairableException("launch needs `app` (a name such as notepad, or a full path).")
        before = await self._call("list_apps", {})
        running = {a.get("pid") for a in before.get("apps") or [] if a.get("running")}
        key = "path" if (":" in app or "\\" in app or "/" in app) else "name"
        await audit_log.append_record({"tool": "computer_use", "action": "launch", "app": app,
                                       "context": getattr(self.agent.context, "id", "")})
        data = await self._call("launch_app", {key: app, "creates_new_application_instance": True})
        pid = data.get("pid")
        if pid and pid not in running:
            context = self.agent.context
            workspace.register_app(
                pid, label=app, context_id=str(getattr(context, "id", "")),
                agent_name=str(getattr(self.agent, "agent_name", "")),
                profile=str(getattr(getattr(self.agent, "config", None), "profile", "") or ""),
                job_id=str((context.get_data("_parallel_job_id") if hasattr(context, "get_data") else "") or ""),
            )
            note = "New process, opened by the agent: input to it needs no extra approval."
        else:
            note = ("This attached to an app that was ALREADY running - it is the user's. "
                    "Input to it asks the user first; never type into an existing document.")
        wins = "; ".join(f"window_id {w.get('window_id')} {w.get('title')!r}" for w in data.get("windows") or [])
        return self._msg(f"Launched {app}: pid {pid}. {note}\n{wins or 'No window yet - use action=windows.'}")

    async def _click(self, cfg, pid=None, element_token=None, x=None, y=None, button=None, count=None, window_id=None, **kwargs) -> Response:
        if not element_token and (x is None or y is None):
            raise RepairableException("click needs `element_token` (from inspect) or `x` and `y`.")
        fg = self._delivery(kwargs)
        label = self._data(_LABELS_KEY, {}).get(element_token, "")
        args = {"element_token": element_token, "x": x, "y": y, "button": button, "count": count}
        await self._guard("click", pid, foreground=bool(fg), args=args)
        data = await self._call("click", {"pid": int(pid) if pid else None, "window_id": window_id,
                                          **args, "delivery_mode": fg})
        if element_token:
            self.agent.context.data[_FOCUS_KEY] = label
        return self._msg(self._summary(data))

    async def _type(self, cfg, pid=None, text="", window_id=None, element_token=None, **kwargs) -> Response:
        if not isinstance(text, str) or not text:
            raise RepairableException("type needs `text`.")
        if pid in (None, ""):
            raise RepairableException("type needs `pid` - never type without naming the target window.")
        label = self._data(_LABELS_KEY, {}).get(element_token) if element_token else self.agent.context.data.get(_FOCUS_KEY, "")
        fg = self._delivery(kwargs)
        await self._guard("type", pid, element_label=label or "", foreground=bool(fg),
                          args={"text": text, "element_token": element_token})
        data = await self._call("type_text", {"pid": int(pid), "window_id": window_id, "element_token": element_token,
                                              "text": text, "delivery_mode": fg})
        return self._msg(self._summary(data))

    async def _set_value(self, cfg, pid=None, element_token=None, value="", **kwargs) -> Response:
        if pid in (None, "") or not element_token:
            raise RepairableException("set_value needs `pid` and `element_token` (from inspect).")
        label = self._data(_LABELS_KEY, {}).get(element_token, "")
        await self._guard("set_value", pid, element_label=label, args={"element_token": element_token, "text": value})
        data = await self._call("set_value", {"pid": int(pid), "element_token": element_token, "value": str(value)})
        return self._msg(self._summary(data))

    async def _key(self, cfg, pid=None, key="", window_id=None, **kwargs) -> Response:
        if pid in (None, "") or not key:
            raise RepairableException("key needs `pid` and `key` (e.g. enter, tab, f5).")
        fg = self._delivery(kwargs)
        await self._guard("key", pid, foreground=bool(fg), args={"key": key})
        data = await self._call("press_key", {"pid": int(pid), "window_id": window_id, "key": str(key), "delivery_mode": fg})
        return self._msg(self._summary(data))

    async def _hotkey(self, cfg, pid=None, keys=None, window_id=None, **kwargs) -> Response:
        combo = policy.normalize_keys(keys)
        if pid in (None, "") or len(combo) < 2:
            raise RepairableException("hotkey needs `pid` and `keys`, e.g. [\"ctrl\", \"s\"].")
        fg = self._delivery(kwargs)
        await self._guard("hotkey", pid, keys=combo, foreground=bool(fg), args={"keys": combo})
        data = await self._call("hotkey", {"pid": int(pid), "window_id": window_id, "keys": combo, "delivery_mode": fg})
        return self._msg(self._summary(data))

    async def _scroll(self, cfg, pid=None, direction="down", amount=None, element_token=None, window_id=None, **kwargs) -> Response:
        if pid in (None, ""):
            raise RepairableException("scroll needs `pid`.")
        await self._guard("scroll", pid, args={"direction": direction})
        data = await self._call("scroll", {"pid": int(pid), "window_id": window_id, "direction": str(direction),
                                           "amount": amount, "element_token": element_token,
                                           "delivery_mode": self._delivery(kwargs)})
        return self._msg(self._summary(data))

    async def _menu(self, cfg, pid=None, path=None, window_id=None, **kwargs) -> Response:
        if pid in (None, "") or not path:
            raise RepairableException("menu needs `pid` and `path`, e.g. [\"File\", \"Save\"].")
        path = [str(p) for p in (path if isinstance(path, list) else str(path).split(">"))]
        await self._guard("menu", pid, args={"path": path})
        data = await self._call("invoke_menu", {"pid": int(pid), "window_id": window_id, "path": [p.strip() for p in path]})
        return self._msg(self._summary(data))

    async def _focus(self, cfg, pid=None, window_id=None, **kwargs) -> Response:
        if pid in (None, ""):
            raise RepairableException("focus needs `pid`.")
        await self._guard("focus", pid, foreground=True, args={"window_id": window_id})
        data = await self._call("bring_to_front", {"pid": int(pid), "window_id": window_id})
        return self._msg(self._summary(data))

    async def _close(self, cfg, pid=None, **kwargs) -> Response:
        if pid in (None, ""):
            raise RepairableException("close needs `pid`.")
        if not self._owned(pid):
            raise RepairableException(
                "[computer_use] Refused: close only ends apps the agent opened in this chat. "
                "Ask the user to close their own windows."
            )
        await self._guard("close", pid, args={})
        data = await self._call("kill_app", {"pid": int(pid)})
        workspace.forget_app(pid)
        return self._msg(self._summary(data))

    async def _hand_over(self, cfg, pid=None, to="", **kwargs) -> Response:
        """Give an app this agent owns to a sub-agent below it (bookkeeping only:
        nothing is sent to the app), so the sub-agent can work in it without
        an approval for every input."""
        if pid in (None, "") or not str(to or "").strip():
            raise RepairableException("hand_over needs `pid` and `to` (a sub-agent such as A1).")
        names = {a.agent_name for a in workspace.iter_agents(self.agent.context)}
        target = f"A{workspace.agent_number(to)}"
        if target not in names:
            raise RepairableException(
                f"{to} is not an agent in this chat. Start the sub-agent first (call_subordinate), then hand it over."
            )
        try:
            entry = workspace.hand_over(self._context_id(), pid, int(getattr(self.agent, "number", 0) or 0), target)
        except ValueError as exc:
            raise RepairableException(f"[computer_use] {exc}")
        return self._msg(f"{entry.label} (pid {pid}) now belongs to {target}; you still own it too.")

    async def _stop_driver(self, cfg, **kwargs) -> Response:
        return self._msg(driver.stop(driver.find_executable(cfg)) or "Stopped.")

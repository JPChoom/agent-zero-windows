"""Agent-facing tool: typed, read-only questions about this Windows machine.

Every call: validate (helpers/validate.py) -> kill switch -> audit for the
sensitive reads -> run the source off the event loop with a timeout ->
compact, capped, redacted text. The result is wrapped as untrusted content
by the history extension like any non-A0 tool result: process names, window
titles, event messages and app names can carry text written by others.
"""

from __future__ import annotations

import asyncio

from helpers import audit_log, kill_switch
from helpers.tool import Response, Tool
from plugins._windows_intel.helpers import config as wcfg
from plugins._windows_intel.helpers import fmt, schema, sources_local, sources_ps, validate

# Reads worth a line in the audit log (what was asked, never the output).
_AUDITED = {"registry", "env", "events"}


class WindowsInfo(Tool):

    async def execute(self, action: str = "", **kwargs) -> Response:
        cfg = wcfg.get_config(self.agent)
        try:
            action, args = validate.validate(
                action, kwargs, default_limit=cfg["default_limit"], max_limit=cfg["max_limit"]
            )
        except ValueError as exc:
            return self._msg(f"windows_info: {exc}. Use action=help for the list of actions and arguments.")

        if action == "help":
            return self._msg(schema.help_text(args.get("topic", "")))
        if kill_switch.is_tripped():
            return self._msg(kill_switch.denial_message())

        if action in _AUDITED or (action == "processes" and args.get("cmdline")):
            await audit_log.append_record({
                "tool": "windows_info", "action": action, "arguments": args,
                "context": getattr(getattr(self.agent, "context", None), "id", ""),
            })

        try:
            text = await asyncio.wait_for(
                asyncio.to_thread(self._run, action, args, cfg), timeout=cfg["ps_timeout_seconds"] + 15
            )
        except asyncio.TimeoutError:
            text = "windows_info: the query took too long and was stopped; narrow it with filters."
        except sources_ps.NeedsAdmin as exc:
            text = f"windows_info: {exc}"
        except sources_ps.PsError as exc:
            text = f"windows_info {action}: {exc}"
        except Exception as exc:  # a broken source must not end the agent's turn
            text = f"windows_info {action} failed: {type(exc).__name__}: {exc}"
        return self._msg(text)

    def _msg(self, text: str) -> Response:
        return Response(message=text, break_loop=False)

    # -- dispatch (runs in a worker thread) --------------------------------------------

    def _run(self, action: str, args: dict, cfg: dict) -> str:
        timeout = cfg["ps_timeout_seconds"]
        local = {
            "processes": sources_local.processes,
            "services": sources_local.services,
            "network": sources_local.network,
            "ports": sources_local.ports,
            "windows": sources_local.windows,
            "env": sources_local.env,
            "registry": sources_local.registry,
        }
        if action in local:
            return local[action](args, cfg)

        if action == "system":
            text = sources_local.system(args, cfg)
            if args.get("gpu"):
                gpus = sources_ps.run_script("gpu", {}, timeout) or []
                text += "\n" + "\n".join(f"gpu: {g['name']} (driver {g['driver']}, {g['mode']})" for g in gpus)
            return text

        if action == "disks":
            text = sources_local.disks(args, cfg)
            if args.get("health"):
                rows = [[d["name"], d["media"], d["bus"], fmt.human_bytes(d["size"]), d["health"], d["status"]]
                        for d in (sources_ps.run_script("disk_health", {}, timeout) or [])]
                text += "\n\nphysical disks:\n" + fmt.table(
                    ["disk", "media", "bus", "size", "health", "status"], rows, limit=50,
                    max_chars=cfg["max_output_chars"] // 2)
            return text

        if action == "apps":
            store_rows = None
            if args.get("store"):
                store_rows = [[p["name"], p["version"], p["publisher"], "", "store"]
                              for p in (sources_ps.run_script("store_apps", {"name": args.get("name")}, timeout) or [])]
            return sources_local.apps(args, cfg, store_rows)

        if action == "startup":
            data = sources_ps.run_script("tasks", {"state": "all", "include_microsoft": False,
                                                   "logon_only": True, "limit": 100}, timeout) or {}
            task_rows = [[t["name"], "logon/boot scheduled task", t["state"].lower(), fmt.redact(t["exe"])]
                         for t in data.get("rows", [])]
            return sources_local.startup(args, cfg, task_rows)

        if action == "tasks":
            data = sources_ps.run_script("tasks", {**args, "logon_only": False}, timeout) or {}
            rows = [[t["path"] + t["name"], t["state"], t["next"], t["last"], t["result"], fmt.redact(t["exe"])]
                    for t in data.get("rows", [])]
            return fmt.table(["task", "state", "next run", "last run", "last result", "action"], rows,
                             limit=args["limit"], total=data.get("total", len(rows)),
                             hint="narrow with name= or include_microsoft=false",
                             max_chars=cfg["max_output_chars"], widths={"action": 140})

        if action == "events":
            if args["log"].strip().lower() == "security":
                raise sources_ps.NeedsAdmin(
                    "the Security log needs administrator rights, and Agent Zero runs as a standard user. "
                    "Tell the user instead of retrying."
                )
            ps_args = {"log": args["log"], "level": args["level"], "since_hours": args["since"],
                       "provider": args.get("provider"), "event_id": args.get("event_id"), "limit": args["limit"]}
            events = sources_ps.run_script("events", ps_args, timeout) or []
            rows = [[e["t"], e["level"], e["provider"], e["id"], fmt.redact(e["msg"])] for e in events]
            hours = args["since"]
            span = f"{hours:g}h" if hours < 48 else f"{hours / 24:g}d"
            head = f"{args['log']} log, {args['level']} and worse, last {span}:"
            return head + "\n" + fmt.table(["time", "level", "source", "id", "message"], rows, limit=args["limit"],
                                           hint="narrow with provider=, event_id= or since=",
                                           max_chars=cfg["max_output_chars"], widths={"message": 300})

        if action == "devices":
            data = sources_ps.run_script("devices", args, timeout) or {}
            rows = [[d["name"], d["cls"], d["status"], "" if d["problem"] in ("", "CM_PROB_NONE") else d["problem"], d["maker"]]
                    for d in data.get("rows", [])]
            return fmt.table(["device", "class", "status", "problem", "manufacturer"], rows, limit=args["limit"],
                             total=data.get("total", len(rows)), hint="narrow with device_class= or problems_only=true",
                             max_chars=cfg["max_output_chars"])

        return f"windows_info: no source for {action}"

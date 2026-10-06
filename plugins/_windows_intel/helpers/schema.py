"""The windows_info action catalog: which actions exist and what each argument
may be. Data only (no Agent Zero imports); helpers/validate.py enforces it
and `help` renders it, so the always-on prompt can stay one line long.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Arg:
    kind: str                        # name | int | bool | enum | duration | regpath | regvalue
    doc: str = ""
    choices: tuple[str, ...] = ()
    lo: int = 0
    hi: int = 0
    default: Any = None
    required: bool = False


@dataclass(frozen=True)
class Action:
    summary: str
    args: dict[str, Arg] = field(default_factory=dict)


LIMIT = Arg("int", "most rows to return", lo=1, hi=500, default=None)  # default/hi come from config


ACTIONS: dict[str, Action] = {
    "system": Action("OS version/build, uptime, CPU, memory, optional GPU", {
        "gpu": Arg("bool", "also list graphics adapters (slower)", default=False),
    }),
    "processes": Action("running processes", {
        "name": Arg("name", "substring of the process name"),
        "pid": Arg("int", "one process id", lo=0, hi=4194304),
        "user": Arg("enum", "whose processes", choices=("me", "all"), default="me"),
        "sort": Arg("enum", "order", choices=("cpu", "memory", "name", "started"), default="memory"),
        "cmdline": Arg("bool", "include the (redacted) command line", default=False),
        "limit": LIMIT,
    }),
    "services": Action("Windows services", {
        "name": Arg("name", "substring of the service or display name"),
        "status": Arg("enum", "state", choices=("running", "stopped", "paused", "all"), default="all"),
        "start_type": Arg("enum", "startup type", choices=("automatic", "manual", "disabled", "all"), default="all"),
        "limit": LIMIT,
    }),
    "apps": Action("installed desktop apps (and Store apps)", {
        "name": Arg("name", "substring of the app name"),
        "store": Arg("bool", "also list Microsoft Store apps (slower)", default=False),
        "limit": LIMIT,
    }),
    "startup": Action("what starts at sign-in: Run keys, Startup folders, logon tasks"),
    "tasks": Action("scheduled tasks", {
        "name": Arg("name", "substring of the task name"),
        "state": Arg("enum", "task state", choices=("ready", "running", "disabled", "all"), default="all"),
        "include_microsoft": Arg("bool", "include built-in Microsoft tasks", default=False),
        "limit": LIMIT,
    }),
    "events": Action("Event Viewer entries (Security log needs administrator)", {
        "log": Arg("name", "log name, e.g. System, Application", default="System"),
        "level": Arg("enum", "minimum severity", choices=("critical", "error", "warning", "information"), default="error"),
        "since": Arg("duration", "how far back, e.g. 30m, 24h, 7d", default=24.0),
        "provider": Arg("name", "event source"),
        "event_id": Arg("int", "one event id", lo=0, hi=65535),
        "limit": Arg("int", "most events (max 100)", lo=1, hi=100, default=20),
    }),
    "devices": Action("Plug and Play devices", {
        "problems_only": Arg("bool", "only devices reporting a problem", default=False),
        "device_class": Arg("name", "device class, e.g. Display, Net"),
        "limit": LIMIT,
    }),
    "disks": Action("volumes: size and free space (optionally physical disk health)", {
        "health": Arg("bool", "include physical disk health (slower)", default=False),
    }),
    "network": Action("network adapters, status and addresses"),
    "ports": Action("TCP/UDP ports and the process using them (your own processes)", {
        "listening": Arg("bool", "only listening ports", default=True),
        "process": Arg("name", "substring of the process name"),
        "limit": LIMIT,
    }),
    "windows": Action("visible top-level windows", {
        "process": Arg("name", "substring of the process name"),
        "include_minimized": Arg("bool", "include minimized windows", default=False),
    }),
    "registry": Action("read a registry key (secrets masked)", {
        "path": Arg("regpath", "e.g. HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", required=True),
        "value": Arg("regvalue", "one value name instead of the whole key"),
        "depth": Arg("int", "0 = this key, 1 = also list subkeys", lo=0, hi=1, default=0),
    }),
    "env": Action("environment variables (secret-looking names masked)", {
        "scope": Arg("enum", "which variables", choices=("process", "user", "machine"), default="user"),
    }),
    "help": Action("describe an action's arguments", {
        "topic": Arg("name", "action name"),
    }),
}


def help_text(topic: str = "") -> str:
    topic = (topic or "").strip().lower()
    if topic in ACTIONS:
        action = ACTIONS[topic]
        lines = [f"{topic}: {action.summary}"]
        for name, a in action.args.items():
            bits = [a.kind]
            if a.choices:
                bits = ["|".join(a.choices)]
            if a.kind == "int" and (a.lo or a.hi):
                bits.append(f"{a.lo}-{a.hi or 'cfg'}")
            if a.default is not None:
                bits.append(f"default {a.default}")
            if a.required:
                bits.append("required")
            lines.append(f"  {name} ({', '.join(bits)}): {a.doc}")
        if not action.args:
            lines.append("  (no arguments)")
        return "\n".join(lines)
    return "windows_info actions (use action=help topic=<action> for arguments):\n" + "\n".join(
        f"  {name}: {a.summary}" for name, a in ACTIONS.items()
    )

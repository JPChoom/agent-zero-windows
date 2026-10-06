"""Thin client for trycua's cua-driver (MIT, https://github.com/trycua/cua).

The driver is a separate, signed executable the user installs into
`usr/cua-driver/<version>/` (git-ignored). This module never downloads it.
It starts the driver's daemon on demand (`serve --permission-mode standard`,
hidden, no console) and sends one `cua-driver call <tool>` per action with
the JSON arguments on stdin - stdin, because PowerShell-style argv quoting
mangles JSON.

Every call carries a session label so element tokens from `inspect` stay
valid for the following click/type in the same chat.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
from pathlib import Path

from helpers import files

DEFAULTS = {
    "control_enabled": False,
    "driver_path": "",
    "disable_telemetry": True,
    "max_elements": 150,
    "call_timeout_seconds": 60,
}

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


class DriverError(Exception):
    pass


def get_config(agent=None) -> dict:
    from helpers import plugins

    cfg = plugins.get_plugin_config("_computer_use", agent=agent) or {}
    out = {k: cfg.get(k, v) for k, v in DEFAULTS.items()}
    out["control_enabled"] = bool(out["control_enabled"])
    out["disable_telemetry"] = bool(out["disable_telemetry"])
    try:
        out["max_elements"] = max(20, int(out["max_elements"]))
    except (TypeError, ValueError):
        out["max_elements"] = DEFAULTS["max_elements"]
    try:
        out["call_timeout_seconds"] = max(5, int(out["call_timeout_seconds"]))
    except (TypeError, ValueError):
        out["call_timeout_seconds"] = DEFAULTS["call_timeout_seconds"]
    return out


def _version_key(name: str) -> tuple:
    return tuple(int(p) if p.isdigit() else 0 for p in re.split(r"[.\-]", name))


def find_executable(cfg: dict) -> str:
    """Configured path, else the newest usr/cua-driver/<version>/cua-driver.exe."""
    configured = str(cfg.get("driver_path") or "").strip()
    if configured:
        if Path(configured).is_file():
            return configured
        raise DriverError(f"driver_path {configured!r} does not exist.")
    root = Path(files.get_abs_path("usr", "cua-driver"))
    candidates = sorted(
        (p for p in root.glob("*/cua-driver.exe") if p.is_file()),
        key=lambda p: _version_key(p.parent.name),
        reverse=True,
    ) if root.is_dir() else []
    if not candidates:
        raise DriverError(
            "cua-driver is not installed. Download the signed Windows build from "
            "https://github.com/trycua/cua/releases (cua-driver-rs-<version>-windows-x86_64-binary.zip), "
            "check its SHA-256 against the release page, and extract it to "
            "usr/cua-driver/<version>/. See plugins/_computer_use/README.md."
        )
    return str(candidates[0])


def _run(exe: str, args: list[str], stdin: str | None = None, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        [exe, *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=_NO_WINDOW,
    )


def is_running(exe: str) -> bool:
    try:
        p = _run(exe, ["status"], timeout=15)
    except Exception:
        return False
    return p.returncode == 0 and "is running" in (p.stdout or "")


_telemetry_checked: set[str] = set()


def ensure_running(exe: str, cfg: dict) -> None:
    if cfg.get("disable_telemetry") and exe not in _telemetry_checked:
        try:
            _run(exe, ["telemetry", "disable"], timeout=15)
        finally:
            _telemetry_checked.add(exe)
    if is_running(exe):
        return
    subprocess.Popen(
        [exe, "serve", "--permission-mode", "standard"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=_NO_WINDOW | _DETACHED,
        close_fds=True,
        cwd=os.path.dirname(exe),
    )
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if is_running(exe):
            return
        time.sleep(0.5)
    raise DriverError("cua-driver daemon did not start within 15 seconds.")


def stop(exe: str) -> str:
    p = _run(exe, ["stop"], timeout=20)
    return (p.stdout or p.stderr or "").strip()


def call_sync(exe: str, tool: str, args: dict, timeout: int) -> dict:
    p = _run(exe, ["call", tool], stdin=json.dumps(args), timeout=timeout)
    text = (p.stdout or "").strip()
    try:
        data = json.loads(text) if text else {}
    except json.JSONDecodeError:
        data = {"summary": text}
    if p.returncode != 0 and not data:
        raise DriverError((p.stderr or text or f"cua-driver call {tool} failed").strip()[:800])
    if not isinstance(data, dict):
        data = {"result": data}
    return data


async def call(agent, tool: str, args: dict) -> dict:
    cfg = get_config(agent)
    exe = find_executable(cfg)
    await asyncio.to_thread(ensure_running, exe, cfg)
    return await asyncio.to_thread(call_sync, exe, tool, args, cfg["call_timeout_seconds"])

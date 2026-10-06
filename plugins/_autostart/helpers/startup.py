"""The per-user Windows Startup entry that launches Agent Zero at logon.

One value under HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run:
no admin rights, shown (and switchable) in Task Manager > Startup apps,
removed completely by `disable()`. Task Manager's own on/off switch lives in
...\\Explorer\\StartupApproved\\Run; it is reported, and cleared on enable so
"enable" here really means enabled.

All registry access goes through `_Registry` so tests can run against a
fake one instead of the real Startup list.
"""

from __future__ import annotations

from pathlib import Path

VALUE_NAME = "AgentZeroForWindows"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"

ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = ROOT / "plugins" / "_autostart" / "launch_agent_zero.pyw"


class _Registry:
    """Minimal HKCU access (winreg)."""

    def get(self, key: str, name: str):
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                return winreg.QueryValueEx(k, name)[0]
        except FileNotFoundError:
            return None

    def set_str(self, key: str, name: str, value: str) -> None:
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)

    def delete(self, key: str, name: str) -> None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, name)
        except FileNotFoundError:
            pass


REGISTRY = _Registry()


def pythonw() -> Path:
    return ROOT / ".venv" / "Scripts" / "pythonw.exe"


def command() -> str:
    return f'"{pythonw()}" "{LAUNCHER}"'


def status(reg=None) -> dict:
    reg = reg or REGISTRY
    current = reg.get(RUN_KEY, VALUE_NAME)
    approved = reg.get(APPROVED_KEY, VALUE_NAME)
    # First byte: even (0x02/0x06) = enabled, odd (0x03/0x07) = switched off in Task Manager.
    off_in_task_manager = bool(approved) and isinstance(approved, (bytes, bytearray)) and approved[0] % 2 == 1
    return {
        "enabled": bool(current) and not off_in_task_manager,
        "registered": bool(current),
        "disabled_in_task_manager": off_in_task_manager,
        "points_here": current == command(),
        "command": current or "",
        "expected_command": command(),
        "launcher_ok": LAUNCHER.is_file() and pythonw().is_file(),
    }


def enable(reg=None) -> dict:
    reg = reg or REGISTRY
    if not (LAUNCHER.is_file() and pythonw().is_file()):
        raise FileNotFoundError(f"launcher or {pythonw()} is missing; set up the .venv first (see README Install).")
    reg.set_str(RUN_KEY, VALUE_NAME, command())
    reg.delete(APPROVED_KEY, VALUE_NAME)
    return status(reg)


def disable(reg=None) -> dict:
    reg = reg or REGISTRY
    reg.delete(RUN_KEY, VALUE_NAME)
    reg.delete(APPROVED_KEY, VALUE_NAME)
    return status(reg)

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

_DENIED_PATTERNS = (
    r"(?i)\b(?:invoke-webrequest|iwr|curl|wget|certutil|bitsadmin)\b",
    r"(?i)\b(?:reg(?:\.exe)?\s+add|schtasks|sc(?:\.exe)?\s+create|new-service)\b",
    r"(?i)\b(?:mimikatz|procdump|sekurlsa|credential)\b",
    r"(?i)\b(?:encodedcommand|-enc\b|frombase64string)\b",
    r"(?i)\b(?:remove-item|del|erase|rd|rmdir)\b[^\r\n]*(?:\\windows|\\program files|\\users\\[^\\]+\\(?:appdata|ntuser))",
    r"(?i)\b(?:shutdown|restart-computer|stop-computer|format|diskpart|bcdedit)\b",
)


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _work_root() -> Path:
    configured = os.getenv("TERMINAL_ACCESS_ROOT", r"C:\a0\usr\workdir")
    return Path(configured).expanduser().resolve()


def _validate(command: str, shell: str) -> tuple[bool, str]:
    if not _env_bool("TERMINAL_ACCESS_ENABLED"):
        return False, "Terminal Access is disabled. Set TERMINAL_ACCESS_ENABLED=true only after reviewing the security policy."
    if shell.lower() not in {"powershell", "cmd"}:
        return False, "Unsupported shell. Use 'powershell' or 'cmd'."
    if not command or len(command) > 20000:
        return False, "Command is empty or exceeds the 20,000-character limit."
    for pattern in _DENIED_PATTERNS:
        if re.search(pattern, command):
            return False, "Command rejected by the host-execution safety policy."
    return True, ""


def execute_command(command: str, shell: str = "powershell") -> dict[str, Any]:
    allowed, error = _validate(command, shell)
    if not allowed:
        return {"status": "error", "output": None, "error": error}

    root = _work_root()
    root.mkdir(parents=True, exist_ok=True)
    timeout = max(1, min(int(os.getenv("TERMINAL_ACCESS_TIMEOUT_SECONDS", "30")), 300))
    max_output = max(4096, min(int(os.getenv("TERMINAL_ACCESS_MAX_OUTPUT_BYTES", "1048576")), 10 * 1024 * 1024))

    argv = (
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command]
        if shell.lower() == "powershell"
        else ["cmd.exe", "/d", "/s", "/c", command]
    )
    env = os.environ.copy()
    for key in list(env):
        if any(token in key.upper() for token in ("API_KEY", "TOKEN", "SECRET", "PASSWORD")):
            env.pop(key, None)

    try:
        result = subprocess.run(
            argv, cwd=str(root), env=env, capture_output=True, text=False,
            timeout=timeout, shell=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        stdout = (result.stdout or b"")[:max_output].decode(errors="replace")
        stderr = (result.stderr or b"")[:max_output].decode(errors="replace")
        truncated = len(result.stdout or b"") > max_output or len(result.stderr or b"") > max_output
        suffix = "\n[output truncated]" if truncated else ""
        return {
            "status": "success" if result.returncode == 0 else "error",
            "output": stdout + suffix,
            "error": (stderr + suffix) if result.returncode else None,
            "returncode": result.returncode,
            "working_directory": str(root),
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "output": None, "error": f"Command timed out after {timeout} seconds."}
    except Exception as exc:
        return {"status": "error", "output": None, "error": f"Command execution failed: {exc}"}

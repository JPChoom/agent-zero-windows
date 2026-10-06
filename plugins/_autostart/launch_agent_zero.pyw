"""Start Agent Zero at Windows logon, without a window.

Run by pythonw.exe from the per-user Startup entry that the Start at logon
plugin writes (HKCU\\...\\Run). It:

1. exits if something already answers on the WebUI port (a second copy would
   fail to bind anyway, after touching state on the way);
2. starts `.venv\\Scripts\\python.exe run_ui.py` with CREATE_NO_WINDOW - a
   hidden console rather than none, so the terminals, tunnel and tools the
   server starts inherit it instead of each opening a visible window;
3. sends the server's output to logs/autostart.log (rotated at 5 MB).
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "logs" / "autostart.log"
DEFAULT_PORT = 5000  # runtime.get_web_ui_port's fallback


def web_ui_port() -> int:
    env = ROOT / "usr" / ".env"
    try:
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "WEB_UI_PORT":
                return int(value.strip().strip('"').strip("'")) or DEFAULT_PORT
    except (OSError, ValueError):
        pass
    return DEFAULT_PORT


def already_running(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def python_exe() -> str:
    venv = ROOT / ".venv" / "Scripts" / "python.exe"
    if venv.is_file():
        return str(venv)
    exe = Path(sys.executable)
    console = exe.with_name("python.exe")
    return str(console if console.is_file() else exe)


def open_log():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    if LOG.exists() and LOG.stat().st_size > 5 * 1024 * 1024:
        LOG.replace(LOG.with_suffix(".log.1"))
    return open(LOG, "a", encoding="utf-8", errors="replace", buffering=1)


def main() -> None:
    os.chdir(ROOT)
    log = open_log()
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    port = web_ui_port()
    if already_running(port):
        log.write(f"[{stamp}] autostart: port {port} already answers, Agent Zero is running - nothing to do.\n")
        return
    log.write(f"[{stamp}] autostart: starting Agent Zero on port {port}\n")
    log.flush()
    subprocess.Popen(
        [python_exe(), "run_ui.py"],
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
    )


if __name__ == "__main__":
    main()

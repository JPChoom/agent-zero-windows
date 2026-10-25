"""Agent Zero owns a local llama.cpp server (`llama-server.exe`).

Settings: Settings > Agent > Models > Local model server (helpers/local_server.py
turns them into a ServerConfig; api/llama_server.py is the control endpoint;
extensions/python/job_loop/_40_llama_server.py starts it and applies saved
changes).

One supervised process per A0W instance, bound to 127.0.0.1 only. It is one
more model provider (`llama_cpp` in conf/model_providers.yaml); LM Studio
and every other provider keep working.

What "running" means here is stricter than "the port answers":
- the process is the one we started (pid + start time, so a reused pid or a
  foreign program on the port is never mistaken for it),
- /health reports ready,
- /v1/models reports the model we asked for (the alias we passed).

Lifecycle:
- start: refuse if the binary or model is missing, the port is taken by
  something else, or (NVIDIA only) free VRAM is clearly too small; then
  launch hidden, log to usr/logs/llama-server.log and wait for readiness.
- monitor: a background thread notices an unexpected exit and restarts with
  backoff (RESTART_BACKOFF), giving up after MAX_RESTARTS within
  RESTART_WINDOW and notifying the user.
- stop: on request and at A0W exit. A server left behind by a forced kill is
  found through the state file on the next start: adopted when it is
  identical (same binary, model, arguments) and healthy, otherwise stopped.
  Either way nothing is orphaned.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from helpers import files

CREATE_NO_WINDOW = 0x08000000
HOST = "127.0.0.1"
RESTART_BACKOFF = (5.0, 15.0, 45.0)
MAX_RESTARTS = 3
RESTART_WINDOW = 600.0
MONITOR_INTERVAL = 2.0
LOG_MAX_BYTES = 5 * 1024 * 1024
VRAM_HEADROOM = 1.10
# A leftover process is only treated as our server if its name contains this.
PROCESS_NAME_HINT = "llama-server"

# Arguments that would change where the server listens or what it serves;
# the supervisor owns those. --host 0.0.0.0 would expose the model to the LAN.
FORBIDDEN_ARGS = {"--host", "--port", "--path", "--ssl-key-file", "--ssl-cert-file", "-m", "--model", "--alias"}


class SupervisorError(Exception):
    """A refusal or failure with a message meant for the user."""


@dataclass
class ServerConfig:
    binary: str
    model: str
    port: int = 8090
    context_size: int = 8192
    gpu_layers: int = 99
    threads: int = 0
    parallel: int = 1
    extra_args: list[str] = field(default_factory=list)
    vram_check: bool = True
    startup_timeout: float = 300.0
    # Arguments placed between the binary and the server's own arguments
    # (never from settings; tests run a Python stand-in this way).
    launcher_prefix: list[str] = field(default_factory=list)

    @property
    def alias(self) -> str:
        return Path(self.model).stem

    def command(self) -> list[str]:
        cmd = [
            self.binary, *self.launcher_prefix, "-m", self.model, "--alias", self.alias,
            "--host", HOST, "--port", str(self.port),
            "-c", str(self.context_size), "-ngl", str(self.gpu_layers), "-np", str(self.parallel),
        ]
        if self.threads > 0:
            cmd += ["-t", str(self.threads)]
        return cmd + list(self.extra_args)

    def identity(self) -> str:
        """Changes whenever anything that defines the running server changes."""
        return hashlib.sha256(json.dumps(self.command()).encode("utf-8")).hexdigest()[:16]


def default_binary() -> str:
    return files.get_abs_path("usr", "llama-cpp", "bin", "llama-server.exe")


def state_path() -> str:
    return files.get_abs_path("usr", "llama-cpp", "server.json")


def log_path() -> str:
    return files.get_abs_path("usr", "logs", "llama-server.log")


def parse_extra_args(text) -> list[str]:
    import shlex

    if isinstance(text, (list, tuple)):
        args = [str(a) for a in text if str(a).strip()]
    else:
        args = shlex.split(str(text or ""), posix=False)
    for arg in args:
        name = arg.split("=", 1)[0].lower()
        if name in FORBIDDEN_ARGS:
            raise SupervisorError(f"Extra argument {name} is set by Agent Zero and cannot be overridden.")
    return args


def config_from_settings(cfg: dict) -> ServerConfig:
    def as_int(key, default):
        try:
            return int(cfg.get(key, default))
        except (TypeError, ValueError):
            return default

    return ServerConfig(
        binary=str(cfg.get("binary_path") or "").strip() or default_binary(),
        model=str(cfg.get("model_path") or "").strip(),
        port=as_int("port", 8090),
        context_size=as_int("context_size", 8192),
        gpu_layers=as_int("gpu_layers", 99),
        threads=as_int("threads", 0),
        parallel=max(1, as_int("parallel", 1)),
        extra_args=parse_extra_args(cfg.get("extra_args", "")),
        vram_check=bool(cfg.get("vram_check", True)),
        startup_timeout=float(as_int("startup_timeout_seconds", 300)),
    )


# ------------------------------------------------------------------ probes

def _http_json(port: int, path: str, timeout: float = 2.0) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}{path}", timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8") or "{}")
        except Exception:
            body = {}
        return exc.code, body
    except Exception:
        return 0, {}


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((HOST, port)) == 0


PORT_RELEASE_SECONDS = 5.0


def _can_bind(port: int) -> bool:
    # Binding, not connecting: repeated connects to a listener that never
    # accepts fill its backlog and then fail, which would read as "free".
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((HOST, port))
            return True
        except OSError:
            return False


def wait_port_free(port: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _can_bind(port):
            return True
        time.sleep(0.2)
    return _can_bind(port)


def served_models(port: int) -> list[str]:
    status, body = _http_json(port, "/v1/models")
    if status != 200:
        return []
    return [str(m.get("id", "")) for m in body.get("data", []) if isinstance(m, dict)]


def is_ready(port: int) -> bool:
    status, body = _http_json(port, "/health")
    return status == 200 and str(body.get("status", "ok")).lower() == "ok"


def free_vram_mib() -> int | None:
    """Free memory of the first NVIDIA GPU, or None when it cannot be told."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, creationflags=CREATE_NO_WINDOW,
        ).stdout
        return int(out.strip().splitlines()[0])
    except Exception:
        return None


def _process_identity(pid: int) -> tuple[float, str] | None:
    try:
        import psutil

        proc = psutil.Process(int(pid))
        return proc.create_time(), proc.name().lower()
    except Exception:
        return None


# ------------------------------------------------------------------ supervisor

class Supervisor:
    def __init__(self):
        self._lock = threading.RLock()
        self._proc: subprocess.Popen | None = None
        self._pid: int | None = None
        self._started_at: float | None = None
        self._config: ServerConfig | None = None
        self._stopping = False
        self._adopted = False
        self._restarts: list[float] = []
        self._monitor: threading.Thread | None = None
        self._log = None
        self.last_error = ""
        self.state = "stopped"  # stopped | starting | running | failed

    # -- public ------------------------------------------------------------

    def start(self, config: ServerConfig) -> dict:
        with self._lock:
            if self.state in ("running", "starting") and self._config and self._config.identity() == config.identity():
                return self.status()
            self._stop_locked()
            self._stopping = False
            self._restarts = []
            try:
                self._launch(config)
            except SupervisorError as exc:
                self._stop_locked()
                self.state, self.last_error = "failed", str(exc)
                raise
            return self.status()

    def stop(self) -> dict:
        with self._lock:
            self._stopping = True
            self._stop_locked()
            self.state = "stopped"
            return self.status()

    def status(self) -> dict:
        # No lock: a start can hold it for minutes while a model loads, and
        # the UI polls this. Each field is read once.
        cfg = self._config
        port = cfg.port if cfg else None
        return {
            "state": self.state,
            "pid": self._pid,
            "port": port,
            "api_base": f"http://{HOST}:{port}/v1" if port else "",
            "model": cfg.model if cfg else "",
            "alias": cfg.alias if cfg else "",
            "adopted": self._adopted,
            "restarts": len(self._restarts),
            "last_error": self.last_error,
            "log": log_path(),
        }

    def running_identity(self) -> str:
        """identity() of the settings the running server was started with ("" when not running)."""
        cfg = self._config
        return cfg.identity() if cfg is not None and self.state == "running" else ""

    # -- launch ------------------------------------------------------------

    def _check(self, config: ServerConfig) -> None:
        if not config.model:
            raise SupervisorError("Choose a GGUF model file first.")
        if not os.path.isfile(config.binary):
            raise SupervisorError(f"llama-server not found at {config.binary}. Download it or set its path.")
        if not os.path.isfile(config.model):
            raise SupervisorError(f"Model file not found: {config.model}")
        if not config.model.lower().endswith(".gguf"):
            raise SupervisorError("The model must be a .gguf file.")

    def _check_vram(self, config: ServerConfig) -> None:
        if config.vram_check and config.gpu_layers != 0:
            free = free_vram_mib()
            need = os.path.getsize(config.model) / (1024 * 1024) * VRAM_HEADROOM
            if free is not None and free < need:
                raise SupervisorError(
                    f"Not enough free GPU memory: {free} MiB free, the model needs about {int(need)} MiB. "
                    "Lower GPU layers, close other GPU apps (for example LM Studio), or turn off the VRAM check."
                )

    def _launch(self, config: ServerConfig) -> None:
        self._check(config)
        self._config = config
        if self._try_adopt(config):
            return
        # A leftover server just stopped by _try_adopt can hold the port for
        # a moment after its process exits (seen on Windows), so allow a
        # few seconds before calling the port taken.
        if port_in_use(config.port) and not wait_port_free(config.port, PORT_RELEASE_SECONDS):
            raise SupervisorError(f"Port {config.port} is already used by another program. Choose another port.")
        # After adoption: a server we adopt already holds its VRAM.
        self._check_vram(config)
        self._open_log()
        self.state, self.last_error = "starting", ""
        self._proc = subprocess.Popen(
            config.command(), stdout=self._log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW, cwd=os.path.dirname(config.binary) or None,
        )
        self._pid = self._proc.pid
        ident = _process_identity(self._pid)
        self._started_at = ident[0] if ident else None
        self._adopted = False
        self._write_state(config)
        self._wait_ready(config)
        self.state = "running"
        self._start_monitor()

    def _wait_ready(self, config: ServerConfig) -> None:
        deadline = time.time() + config.startup_timeout
        while time.time() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                self._clear_state()
                raise SupervisorError(f"llama-server exited during startup (code {self._proc.returncode}). See {log_path()}.")
            if is_ready(config.port):
                models = served_models(config.port)
                if config.alias not in models:
                    self._kill()
                    raise SupervisorError(
                        f"The server on port {config.port} reports {models or 'no model'}, not {config.alias}."
                    )
                return
            time.sleep(0.5)
        self._kill()
        raise SupervisorError(f"llama-server was not ready within {int(config.startup_timeout)} s. See {log_path()}.")

    # -- adoption of a server left by a previous run -------------------------

    def _try_adopt(self, config: ServerConfig) -> bool:
        saved = self._read_state()
        if not saved:
            return False
        pid, started = saved.get("pid"), saved.get("started")
        ident = _process_identity(pid) if pid else None
        ours = bool(ident and started and abs(ident[0] - float(started)) < 1.0 and PROCESS_NAME_HINT in ident[1])
        if not ours:
            self._clear_state()  # the process is gone, or the pid now belongs to something else
            return False
        if (saved.get("identity") == config.identity() and is_ready(config.port)
                and config.alias in served_models(config.port)):
            self._proc, self._pid, self._started_at, self._adopted = None, int(pid), float(started), True
            self.state, self.last_error = "running", ""
            self._start_monitor()
            return True
        _terminate_pid(int(pid))  # ours but different settings, or unhealthy: replace it
        self._clear_state()
        return False

    # -- monitor and crash recovery -------------------------------------------

    def _start_monitor(self) -> None:
        if self._monitor and self._monitor.is_alive():
            return
        self._monitor = threading.Thread(target=self._watch, name="llama-server-monitor", daemon=True)
        self._monitor.start()

    def _alive(self) -> bool:
        if self._proc is not None:
            return self._proc.poll() is None
        ident = _process_identity(self._pid) if self._pid else None
        return bool(ident and self._started_at and abs(ident[0] - self._started_at) < 1.0)

    def _watch(self) -> None:
        while True:
            time.sleep(MONITOR_INTERVAL)
            with self._lock:
                if self._stopping or self.state not in ("running",):
                    return
                if self._alive():
                    continue
                config = self._config
                now = time.time()
                self._restarts = [t for t in self._restarts if now - t < RESTART_WINDOW]
                if len(self._restarts) >= MAX_RESTARTS or config is None:
                    self.state = "failed"
                    self.last_error = f"llama-server stopped {MAX_RESTARTS} times in {int(RESTART_WINDOW / 60)} min; not restarting. See {log_path()}."
                    self._clear_state()
                    _notify(self.last_error)
                    return
                delay = RESTART_BACKOFF[min(len(self._restarts), len(RESTART_BACKOFF) - 1)]
                self._restarts.append(now)
                self.state = "starting"
                self.last_error = f"llama-server exited unexpectedly; restarting in {int(delay)} s."
            time.sleep(delay)
            with self._lock:
                if self._stopping:
                    return
                try:
                    self._stop_locked()  # closes the old log, clears the dead process
                    self._monitor = None
                    self._launch(config)
                    return  # _launch started a fresh monitor
                except SupervisorError as exc:
                    self._stop_locked()
                    self.state, self.last_error = "failed", str(exc)
                    _notify(self.last_error)
                    return

    # -- stop ---------------------------------------------------------------

    def _stop_locked(self) -> None:
        had_server = self._pid is not None
        self._kill()
        if had_server:
            # Only our own server's state; a leftover from a previous run is
            # handled (adopted or replaced) by _try_adopt.
            self._clear_state()
        self._proc, self._pid, self._started_at, self._adopted = None, None, None, False
        if self._log:
            try:
                self._log.close()
            except Exception:
                pass
            self._log = None

    def _kill(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=10)
        elif self._proc is None and self._pid and self._alive():
            _terminate_pid(self._pid)

    # -- files --------------------------------------------------------------

    def _open_log(self) -> None:
        path = log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > LOG_MAX_BYTES:
            os.replace(path, path + ".1")
        self._log = open(path, "ab")

    def _write_state(self, config: ServerConfig) -> None:
        path = state_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"pid": self._pid, "started": self._started_at, "port": config.port,
                       "model": config.model, "identity": config.identity()}, fh)

    def _read_state(self) -> dict | None:
        try:
            with open(state_path(), encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _clear_state(self) -> None:
        try:
            os.remove(state_path())
        except OSError:
            pass


def _terminate_pid(pid: int) -> None:
    try:
        import psutil

        proc = psutil.Process(pid)
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except psutil.TimeoutExpired:
            proc.kill()
    except Exception:
        pass


def _notify(message: str) -> None:
    try:
        from helpers.notification import NotificationManager, NotificationPriority, NotificationType

        NotificationManager.send_notification(
            type=NotificationType.ERROR, priority=NotificationPriority.HIGH,
            title="llama.cpp server", message=message, display_time=15,
            group="llama_server", id="llama_server_failed",
        )
    except Exception:
        pass


_supervisor = Supervisor()


def _stop_at_exit() -> None:
    # A0W is exiting: stop the server we started. A forced kill skips this;
    # the next start then adopts or replaces the leftover (_try_adopt).
    try:
        _supervisor.stop()
    except Exception:
        pass


import atexit  # noqa: E402

atexit.register(_stop_at_exit)


def get() -> Supervisor:
    return _supervisor

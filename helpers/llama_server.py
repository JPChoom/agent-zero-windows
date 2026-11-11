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
  something else, or (NVIDIA only) free VRAM is clearly too small for the
  model plus its image projector (`--mmproj`); then launch hidden, log to
  usr/logs/llama-server.log and wait for readiness.
- memory check: once ready, ask Windows how much of the server's GPU memory
  is *shared* (system RAM). A model that does not fit is not refused by the
  driver, it is moved partly into system RAM and runs about 10x slower
  (seen: Q5 27B at 65k context plus Vision, 120 -> 9 tokens/s, model calls
  stalling). Over SPILL_WARN_MIB the status carries `memory_warning` and the
  user is notified.
- monitor: a background thread notices an unexpected exit and restarts with
  backoff (RESTART_BACKOFF), giving up after MAX_RESTARTS within
  RESTART_WINDOW and notifying the user.
- stop: on request and at A0W exit. On Windows the server is also put in a
  Job Object that ends it when A0W's process ends however it ends - closing
  the console window, a crash, Task Manager - none of which run Python's exit
  handlers, so the model stayed in GPU memory. If that fails, a server left
  behind is found through the state file on the next start: adopted when it
  is identical (same binary, model, arguments) and healthy, otherwise
  stopped.

API key: bound to 127.0.0.1 is not private enough. A virtual machine on
NAT with host-loopback access, or any other program, could use the model
(and the GPU) through it, and every endpoint except /health would answer.
So the server is started with `--api-key-file` pointing at a random key kept
in usr/llama-cpp/api_key.txt (created once, so the server's identity stays
the same across starts and the key never appears on a command line), and
A0W sends it on its own calls (`_http_json`, `helpers/local_server.api_key_for`
for model calls). Other programs that should use the server read the file.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
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
# The image projector also needs working memory while it encodes an image.
MMPROJ_EXTRA_MIB = 512
# Shared (system RAM) GPU memory of the server above this means the model
# did not fit. Measured on an RTX 4090, Qwen3.8-27B Q5_K_M at 65k context: a
# server that fits shows 274 MiB idle and ~320 MiB after generating (the
# driver's own host buffers) at full speed; with Vision on it spilled to
# 832 MiB and ran ~10x slower.
SPILL_WARN_MIB = 600
SPILL_SETTLE_SECONDS = 5.0
# A leftover process is only treated as our server if its name contains this.
PROCESS_NAME_HINT = "llama-server"

# Arguments that would change where the server listens or what it serves;
# the supervisor owns those. --host 0.0.0.0 would expose the model to the LAN.
FORBIDDEN_ARGS = {"--host", "--port", "--path", "--ssl-key-file", "--ssl-cert-file", "-m", "--model", "--alias",
                  "--api-key", "--api-key-file"}


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
    api_key_file: str = ""  # --api-key-file: the server refuses every call without the key except /health
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
        if self.api_key_file:
            cmd += ["--api-key-file", self.api_key_file]
        return cmd + list(self.extra_args)

    def identity(self) -> str:
        """Changes whenever anything that defines the running server changes."""
        return hashlib.sha256(json.dumps(self.command()).encode("utf-8")).hexdigest()[:16]


def default_binary() -> str:
    return files.get_abs_path("usr", "llama-cpp", "bin", "llama-server.exe")


def state_path() -> str:
    return files.get_abs_path("usr", "llama-cpp", "server.json")


def api_key_path() -> str:
    return files.get_abs_path("usr", "llama-cpp", "api_key.txt")


def ensure_api_key() -> str:
    """The key file's path, creating a random key the first time."""
    path = api_key_path()
    if not current_api_key():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        files.write_file_atomic(path, secrets.token_urlsafe(32) + "\n")
    return path


def current_api_key() -> str:
    """The server's key, or "" when there is none (never creates one)."""
    try:
        with open(api_key_path(), encoding="utf-8") as fh:
            for line in fh:
                if line.strip() and not line.lstrip().startswith("#"):
                    return line.strip()
    except OSError:
        pass
    return ""


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
    request = urllib.request.Request(f"http://{HOST}:{port}{path}")
    key = current_api_key()
    if key:
        request.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
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


def mmproj_of(config: ServerConfig) -> str:
    """The image projector the server is started with ("" for none)."""
    args = list(config.extra_args)
    for flag in ("--mmproj", "-mm"):
        if flag in args and args.index(flag) + 1 < len(args):
            return args[args.index(flag) + 1]
    return ""


def gpu_shared_mib(pid: int) -> int | None:
    """Shared (system RAM) GPU memory of a process, from Windows' GPU counters.

    None when it cannot be told (not Windows, no counters, a non-English
    Windows whose counter names differ).
    """
    if os.name != "nt":
        return None
    query = (
        f"(Get-Counter '\\GPU Process Memory(pid_{int(pid)}_*)\\Shared Usage' -ErrorAction Stop)"
        ".CounterSamples | Measure-Object -Property CookedValue -Sum | ForEach-Object { [int64]$_.Sum }"
    )
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", query],
            capture_output=True, text=True, timeout=20, creationflags=CREATE_NO_WINDOW,
        ).stdout.strip()
        return int(out) // (1024 * 1024) if out else None
    except Exception:
        return None


def spill_message(shared_mib: int, vision: bool) -> str:
    return (
        f"The model does not fit in GPU memory: {shared_mib} MiB of it is in system RAM, "
        "so it runs many times slower and model calls may stall. "
        + ("Turn Vision off, or " if vision else "")
        + "lower the context size or use a smaller model file (for example Q4_K_M), "
        "and close other GPU apps."
    )


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
        self.memory_warning = ""
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
            "vision": bool(cfg and mmproj_of(cfg)),
            "memory_warning": self.memory_warning,
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
            projector = mmproj_of(config)
            if projector and os.path.isfile(projector):
                need += os.path.getsize(projector) / (1024 * 1024) + MMPROJ_EXTRA_MIB
            if free is not None and free < need:
                raise SupervisorError(
                    f"Not enough free GPU memory: {free} MiB free, the model needs about {int(need)} MiB"
                    + (" with Vision" if projector else "") + ". "
                    "Lower GPU layers, close other GPU apps (for example LM Studio), turn Vision off, "
                    "or turn off the VRAM check."
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
        _end_with_this_process(self._pid)
        ident = _process_identity(self._pid)
        self._started_at = ident[0] if ident else None
        self._adopted = False
        self._write_state(config)
        self._wait_ready(config)
        self.state = "running"
        self._start_monitor()
        self._start_memory_check(config)

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
            _end_with_this_process(self._pid)
            self._start_monitor()
            self._start_memory_check(config)
            return True
        _terminate_pid(int(pid))  # ours but different settings, or unhealthy: replace it
        self._clear_state()
        return False

    # -- GPU memory spill check -------------------------------------------------

    def _start_memory_check(self, config: ServerConfig) -> None:
        self.memory_warning = ""
        pid = self._pid
        threading.Thread(target=self._check_memory, args=(pid, config), name="llama-server-memory",
                         daemon=True).start()

    def _check_memory(self, pid: int | None, config: ServerConfig) -> None:
        time.sleep(SPILL_SETTLE_SECONDS)
        shared = gpu_shared_mib(pid) if pid else None
        if shared is None or shared <= SPILL_WARN_MIB or pid != self._pid:
            return
        self.memory_warning = spill_message(shared, bool(mmproj_of(config)))
        _notify(self.memory_warning, warning=True)

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
        self.memory_warning = ""
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


def _notify(message: str, warning: bool = False) -> None:
    try:
        from helpers.notification import NotificationManager, NotificationPriority, NotificationType

        NotificationManager.send_notification(
            type=NotificationType.WARNING if warning else NotificationType.ERROR,
            priority=NotificationPriority.HIGH,
            title="llama.cpp server", message=message, display_time=30 if warning else 15,
            group="llama_server", id="llama_server_memory" if warning else "llama_server_failed",
        )
    except Exception:
        pass


# -- end the server with A0W (Windows Job Object) ------------------------------

_JOB = None  # handle of this process' kill-on-close job, created on first use


def _kill_on_close_job():
    global _JOB
    if _JOB is not None or os.name != "nt":
        return _JOB
    import ctypes
    from ctypes import wintypes

    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class EXTENDED(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", ctypes.c_uint64 * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = EXTENDED()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):  # extended limits
        kernel32.CloseHandle(job)
        return None
    # The handle is deliberately never closed and not inheritable: it closes
    # when this process ends, and Windows then ends every process in the job.
    _JOB = job
    return _JOB


def _end_with_this_process(pid: int) -> bool:
    """Make Windows end `pid` when A0W's process ends. False if it could not."""
    try:
        job = _kill_on_close_job()
        if not job:
            return False
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x0100 | 0x0001, False, int(pid))  # PROCESS_SET_QUOTA | PROCESS_TERMINATE
        if not handle:
            return False
        try:
            return bool(kernel32.AssignProcessToJobObject(job, handle))
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False


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

"""Windows Job Object-based resource isolation for gate build/test
commands: process-count/memory limits and guaranteed full-process-tree
termination on timeout.

Resource isolation only, not privilege isolation - assigning a process
to a Job Object doesn't run it under a different (restricted) user
account or token. The hand-off doc's "real" broker also needs that
piece, which requires a dedicated restricted Windows account - out of
scope for direct action per this fork's own safety rules (never modify
system/security settings); exact commands for the user to run themselves
were provided when that item came up earlier in this roadmap. This gives
build/test commands memory and process-count limits, and reliable
whole-tree termination on timeout, on top of whatever account they
already run under.

Deliberately does not touch _code_execution's interactive terminal
session (shell_local.py/tty_session.py) - only _coding_controller's own
adapter-run build/test commands (process_runner.py) go through this.

Uses pywin32 (a sys_platform=="win32"-conditional dependency - see
requirements.txt) rather than raw ctypes Job Object structs, which are
fiddly and error-prone to define correctly by hand. Degrades to a no-op
if pywin32 isn't importable (a non-Windows install, or an environment
where it wasn't installed) or if job creation/assignment fails for any
reason - resource limiting is a hardening layer, not something that
should turn a working build gate into a broken one.

CPU rate limiting (JobObjectCpuRateControlInformation) is deliberately
not implemented: it needs its own more involved API (percentage-based
hard-cap flags) for comparatively low value here - a slow build finishing
slowly isn't the failure mode this exists to prevent, unlike unbounded
memory growth or a runaway process fork-bomb, which the limits below do
cover.
"""

import os

try:
    import win32api
    import win32con
    import win32job

    _AVAILABLE = os.name == "nt"
except ImportError:
    _AVAILABLE = False

DEFAULT_MEMORY_LIMIT_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB per process
DEFAULT_MAX_PROCESSES = 64


def is_available() -> bool:
    return _AVAILABLE


class JobHandle:
    """Wraps a Job Object handle. terminate() kills every process
    currently in the job - the whole tree, not just the one this fork
    spawned directly. close() releases the handle without killing
    anything, for the normal "command finished on its own" path."""

    def __init__(self, handle):
        self._handle = handle

    def terminate(self) -> None:
        if self._handle is None:
            return
        try:
            win32job.TerminateJobObject(self._handle, 1)
        except Exception:
            pass  # best-effort - the caller still falls back to killing its own child directly

    def close(self) -> None:
        if self._handle is None:
            return
        try:
            win32api.CloseHandle(self._handle)
        except Exception:
            pass
        self._handle = None


def create_job(
    *,
    memory_limit_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES,
    max_processes: int = DEFAULT_MAX_PROCESSES,
) -> JobHandle | None:
    """Creates a new, unnamed Job Object with the given limits. Returns
    None if pywin32 isn't available or job creation fails for any
    reason - callers must treat that as "no isolation available this
    time", not a hard error that should abort the command."""
    if not _AVAILABLE:
        return None
    try:
        handle = win32job.CreateJobObject(None, "")
        info = win32job.QueryInformationJobObject(handle, win32job.JobObjectExtendedLimitInformation)
        info["BasicLimitInformation"]["LimitFlags"] = (
            win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            | win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            | win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
        )
        info["BasicLimitInformation"]["ActiveProcessLimit"] = max_processes
        info["ProcessMemoryLimit"] = memory_limit_bytes
        win32job.SetInformationJobObject(handle, win32job.JobObjectExtendedLimitInformation, info)
        return JobHandle(handle)
    except Exception:
        return None


def assign_process(job: JobHandle | None, pid: int) -> bool:
    """Assigns the process with `pid` to `job`. Returns True on success.
    A process that can't be assigned (e.g. Windows versions before
    nested-job support, if this process itself is already in a job
    without break-away rights) is a soft failure, not fatal - the
    command still runs, just without this isolation layer for that run."""
    if job is None or job._handle is None:
        return False
    try:
        process_handle = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, False, pid)
    except Exception:
        return False
    try:
        win32job.AssignProcessToJobObject(job._handle, process_handle)
        return True
    except Exception:
        return False
    finally:
        try:
            win32api.CloseHandle(process_handle)
        except Exception:
            pass

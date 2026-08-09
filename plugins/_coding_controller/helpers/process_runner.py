"""Direct, non-interactive subprocess execution for gate commands.

Deliberately bypasses the interactive PTY terminal (_code_execution) - gate
commands need an authoritative exit code and captured stdout/stderr, not a
prompt-detection heuristic layered on top of a shell session.
"""

import asyncio
import os
import time
from dataclasses import dataclass

from . import process_broker


@dataclass
class CommandResult:
    command: list[str]
    exit_code: int | None
    timed_out: bool
    stdout: str
    stderr: str
    duration_ms: int

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


async def run_command(
    args: list[str],
    cwd: str,
    timeout_seconds: int = 300,
    env: dict | None = None,
    enable_process_broker: bool = True,
    memory_limit_mb: int = 2048,
    max_processes: int = 64,
) -> CommandResult:
    if not args:
        return CommandResult(
            command=args, exit_code=None, timed_out=False,
            stdout="", stderr="no command given", duration_ms=0,
        )

    # On Windows, .cmd/.bat launchers (e.g. npm, npx) aren't directly
    # executable via CreateProcess - they need cmd.exe /c to run at all.
    exe = args[0]
    if os.name == "nt" and exe.lower().endswith((".cmd", ".bat")):
        args = ["cmd.exe", "/c", *args]

    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, OSError) as exc:
        return CommandResult(
            command=args, exit_code=None, timed_out=False,
            stdout="", stderr=str(exc), duration_ms=0,
        )

    # Assign the freshly-spawned process to a Job Object so a timeout can
    # kill its whole descendant tree (npm test -> node.exe -> test-runner
    # children), not just this one pid. No-op on non-Windows or when
    # pywin32/job creation isn't available - the command still runs either way.
    job = None
    pid = getattr(proc, "pid", None)
    if enable_process_broker and pid is not None:
        job = process_broker.create_job(
            memory_limit_bytes=memory_limit_mb * 1024 * 1024,
            max_processes=max_processes,
        )
        if job is not None:
            process_broker.assign_process(job, pid)

    try:
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
            timed_out = False
        except asyncio.TimeoutError:
            if job is not None:
                job.terminate()  # kills the whole process tree, not just proc
            else:
                proc.kill()
            await proc.wait()
            stdout_b, stderr_b = b"", b""
            timed_out = True
    finally:
        if job is not None:
            job.close()

    duration_ms = int((time.monotonic() - start) * 1000)
    return CommandResult(
        command=args,
        exit_code=proc.returncode,
        timed_out=timed_out,
        stdout=stdout_b.decode("utf-8", errors="replace"),
        stderr=stderr_b.decode("utf-8", errors="replace"),
        duration_ms=duration_ms,
    )

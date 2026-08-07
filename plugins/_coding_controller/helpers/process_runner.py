"""Direct, non-interactive subprocess execution for gate commands.

Deliberately bypasses the interactive PTY terminal (_code_execution) - gate
commands need an authoritative exit code and captured stdout/stderr, not a
prompt-detection heuristic layered on top of a shell session.
"""

import asyncio
import os
import time
from dataclasses import dataclass


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
    args: list[str], cwd: str, timeout_seconds: int = 300, env: dict | None = None
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

    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_seconds
        )
        timed_out = False
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        stdout_b, stderr_b = b"", b""
        timed_out = True

    duration_ms = int((time.monotonic() - start) * 1000)
    return CommandResult(
        command=args,
        exit_code=proc.returncode,
        timed_out=timed_out,
        stdout=stdout_b.decode("utf-8", errors="replace"),
        stderr=stderr_b.decode("utf-8", errors="replace"),
        duration_ms=duration_ms,
    )

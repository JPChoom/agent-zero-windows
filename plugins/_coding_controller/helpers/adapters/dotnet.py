"""dotnet CLI adapter: restore (optional) and build a .NET project/solution.

Runs the actual dotnet build via direct subprocess invocation, not through
the interactive terminal - this needs an authoritative exit code, not a
prompt-detection heuristic.
"""

import os

from plugins._coding_controller.helpers.diagnostics import parse_dotnet_diagnostics
from plugins._coding_controller.helpers.find_binary import find_executable
from plugins._coding_controller.helpers.process_runner import CommandResult, run_command

_WINDOWS_DOTNET_CANDIDATES = (r"C:\Program Files\dotnet\dotnet.exe",)
_PROJECT_EXTS = (".csproj", ".fsproj", ".vbproj")


def find_dotnet() -> str:
    return find_executable(("dotnet",), _WINDOWS_DOTNET_CANDIDATES)


async def run_gate(project_root: str, cfg: dict) -> dict:
    dotnet = find_dotnet()
    if not dotnet:
        return _skipped("dotnet CLI not found on PATH; install the .NET SDK to enable this gate")

    timeout = cfg.get("command_timeout_seconds", 300)
    target = _find_build_target(project_root)
    stages = []

    if cfg.get("dotnet_restore_first", True):
        restore_cmd = [dotnet, "restore"] + ([target] if target else [])
        restore = await run_command(restore_cmd, cwd=project_root, timeout_seconds=timeout)
        stages.append(_stage("restore", restore, parse_dotnet_diagnostics(restore.stdout + "\n" + restore.stderr)))
        if not restore.passed:
            return _result(stages)

    build_args = cfg.get("dotnet_build_args", "build --no-restore -nologo").split()
    build_cmd = [dotnet] + build_args + ([target] if target else [])
    build = await run_command(build_cmd, cwd=project_root, timeout_seconds=timeout)
    diagnostics = parse_dotnet_diagnostics(build.stdout + "\n" + build.stderr)
    stages.append(_stage("build", build, diagnostics))

    return _result(stages)


def _find_build_target(project_root: str) -> str:
    try:
        entries = os.listdir(project_root)
    except OSError:
        return ""
    sln = next((n for n in entries if n.lower().endswith(".sln")), "")
    if sln:
        return sln
    return next((n for n in entries if n.lower().endswith(_PROJECT_EXTS)), "")


def _stage(name: str, result: CommandResult, diagnostics: list[dict]) -> dict:
    return {
        "name": name,
        "command": " ".join(result.command),
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "passed": result.passed,
        "duration_ms": result.duration_ms,
        "diagnostics": diagnostics,
        "stdout_tail": result.stdout[-2000:],
        "stderr_tail": result.stderr[-2000:],
    }


def _result(stages: list[dict]) -> dict:
    passed = all(s["passed"] for s in stages)
    return {"passed": passed, "skipped": False, "reason": "", "stages": stages}


def _skipped(reason: str) -> dict:
    return {"passed": True, "skipped": True, "reason": reason, "stages": []}

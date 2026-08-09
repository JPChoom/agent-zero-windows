"""Rust adapter: cargo fmt --check -> cargo clippy -> cargo build -> cargo
test.

All four stages run regardless of earlier failures (unlike dotnet.py's
restore, none of these is a hard prerequisite the way "code must be
restored before it can build" is - a failing fmt/clippy check doesn't
prevent build/test from also running and being informative in the same
turn).
"""

from plugins._coding_controller.helpers.find_binary import find_executable
from plugins._coding_controller.helpers.process_runner import CommandResult, run_command


def find_cargo() -> str:
    return find_executable(("cargo",))


async def run_gate(project_root: str, cfg: dict) -> dict:
    cargo = find_cargo()
    if not cargo:
        return _skipped("cargo not found on PATH; install Rust (rustup) to enable this gate")

    timeout = cfg.get("command_timeout_seconds", 300)
    stages = []

    fmt = await run_command([cargo, "fmt", "--", "--check"], cwd=project_root, timeout_seconds=timeout)
    stages.append(_stage("cargo-fmt", fmt))

    clippy = await run_command([cargo, "clippy", "--"], cwd=project_root, timeout_seconds=timeout)
    stages.append(_stage("cargo-clippy", clippy))

    build_args = cfg.get("rust_build_args", "build").split()
    build = await run_command([cargo] + build_args, cwd=project_root, timeout_seconds=timeout)
    stages.append(_stage("cargo-build", build))

    test = await run_command([cargo, "test"], cwd=project_root, timeout_seconds=timeout)
    stages.append(_stage("cargo-test", test))

    return _result(stages)


def _stage(name: str, result: CommandResult) -> dict:
    return {
        "name": name,
        "command": " ".join(result.command),
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "passed": result.passed,
        "duration_ms": result.duration_ms,
        "diagnostics": [],
        "stdout_tail": result.stdout[-2000:],
        "stderr_tail": result.stderr[-2000:],
    }


def _result(stages: list[dict]) -> dict:
    passed = all(s["passed"] for s in stages)
    return {"passed": passed, "skipped": False, "reason": "", "stages": stages}


def _skipped(reason: str) -> dict:
    return {"passed": True, "skipped": True, "reason": reason, "stages": []}

"""Python adapter: ruff (lint + format check) and pytest (test).

Two independent tools rather than dotnet.py's single CLI, so "the
toolchain isn't installed" is judged per-tool: the whole gate is only
skipped if neither ruff nor pytest is found. If only one is available,
its stages run and the other is simply omitted from the result - same
graceful-degradation posture as the rest of this plugin, just applied at
finer granularity than a single skip/run switch.
"""

from plugins._coding_controller.helpers.find_binary import find_executable
from plugins._coding_controller.helpers.process_runner import CommandResult, run_command


def find_ruff() -> str:
    return find_executable(("ruff",))


def find_pytest() -> str:
    return find_executable(("pytest",))


async def run_gate(project_root: str, cfg: dict) -> dict:
    ruff = find_ruff()
    pytest_bin = find_pytest()
    if not ruff and not pytest_bin:
        return _skipped("neither ruff nor pytest found on PATH; install them to enable this gate")

    timeout = cfg.get("command_timeout_seconds", 300)
    stages = []

    if ruff:
        lint = await run_command([ruff, "check", "."], cwd=project_root, timeout_seconds=timeout)
        stages.append(_stage("ruff-check", lint))

        fmt = await run_command([ruff, "format", "--check", "."], cwd=project_root, timeout_seconds=timeout)
        stages.append(_stage("ruff-format", fmt))

    if pytest_bin:
        test_args = cfg.get("python_test_args", "").split()
        test = await run_command([pytest_bin] + test_args, cwd=project_root, timeout_seconds=timeout)
        stages.append(_stage("pytest", test))

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

"""Go adapter: gofmt -l (format check) -> go vet -> go build -> go test.

gofmt is skipped individually (not the whole gate) if it isn't found
alongside go on PATH - it's normally bundled with the Go distribution,
but a minimal/custom install could omit it. `gofmt -l` always exits 0
(it just lists files that need formatting), so "passed" here is
overridden to mean "no files listed" rather than "exit code 0" - the one
place this adapter can't reuse dotnet.py/npm.py's CommandResult.passed
as-is.
"""

from plugins._coding_controller.helpers.find_binary import find_executable
from plugins._coding_controller.helpers.process_runner import CommandResult, run_command


def find_go() -> str:
    return find_executable(("go",))


def find_gofmt() -> str:
    return find_executable(("gofmt",))


async def run_gate(project_root: str, cfg: dict) -> dict:
    go = find_go()
    if not go:
        return _skipped("go CLI not found on PATH; install Go to enable this gate")

    timeout = cfg.get("command_timeout_seconds", 300)
    stages = []

    gofmt = find_gofmt()
    if gofmt:
        fmt = await run_command([gofmt, "-l", "."], cwd=project_root, timeout_seconds=timeout)
        needs_formatting = bool(fmt.stdout.strip())
        stages.append(_stage("gofmt", fmt, passed_override=fmt.passed and not needs_formatting))

    vet = await run_command([go, "vet", "./..."], cwd=project_root, timeout_seconds=timeout)
    stages.append(_stage("go-vet", vet))

    build = await run_command([go, "build", "./..."], cwd=project_root, timeout_seconds=timeout)
    stages.append(_stage("go-build", build))

    test_args = cfg.get("go_test_args", "./...").split()
    test = await run_command([go, "test"] + test_args, cwd=project_root, timeout_seconds=timeout)
    stages.append(_stage("go-test", test))

    return _result(stages)


def _stage(name: str, result: CommandResult, passed_override: bool | None = None) -> dict:
    return {
        "name": name,
        "command": " ".join(result.command),
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "passed": result.passed if passed_override is None else passed_override,
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

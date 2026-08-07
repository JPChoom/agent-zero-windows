"""npm CLI adapter: install (optional) and test an npm project."""

from plugins._coding_controller.helpers.find_binary import find_executable
from plugins._coding_controller.helpers.process_runner import CommandResult, run_command

_WINDOWS_NPM_CANDIDATES = (r"C:\Program Files\nodejs\npm.cmd",)


def find_npm() -> str:
    return find_executable(("npm", "npm.cmd"), _WINDOWS_NPM_CANDIDATES)


async def run_gate(project_root: str, cfg: dict) -> dict:
    npm = find_npm()
    if not npm:
        return _skipped("npm not found on PATH; install Node.js to enable this gate")

    timeout = cfg.get("command_timeout_seconds", 300)
    stages = []

    if cfg.get("npm_install_first", False):
        install = await run_command([npm, "install"], cwd=project_root, timeout_seconds=timeout)
        stages.append(_stage("install", install))
        if not install.passed:
            return _result(stages)

    test_args = cfg.get("npm_test_args", "test").split()
    test = await run_command([npm] + test_args, cwd=project_root, timeout_seconds=timeout)
    stages.append(_stage("test", test))

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

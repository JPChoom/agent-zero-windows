"""Java/Kotlin adapter: detects Maven (pom.xml) or Gradle (build.gradle /
build.gradle.kts) and runs that tool's own test target. "Moderate"
support matching the hand-off doc's own table - one stage (test, which
implies compile for both build tools), no dedicated Checkstyle/ktlint
auto-invocation in this pass.

Prefers the project's own wrapper script (mvnw/gradlew) when present -
the standard convention for pinning a build-tool version without
requiring a global install - falling back to a globally installed
mvn/gradle.
"""

import os
import stat

from plugins._coding_controller.helpers.find_binary import find_executable
from plugins._coding_controller.helpers.process_runner import CommandResult, run_command

_GRADLE_MARKERS = ("build.gradle", "build.gradle.kts")


def find_maven() -> str:
    return find_executable(("mvn",))


def find_gradle() -> str:
    return find_executable(("gradle",))


def _wrapper(project_root: str, name: str) -> str:
    candidates = [name, f"{name}.bat"] if os.name == "nt" else [name]
    for candidate in candidates:
        path = os.path.join(project_root, candidate)
        if os.path.isfile(path):
            if os.name != "nt" and not (os.stat(path).st_mode & stat.S_IEXEC):
                continue
            return path
    return ""


async def run_gate(project_root: str, cfg: dict) -> dict:
    has_pom = os.path.isfile(os.path.join(project_root, "pom.xml"))
    has_gradle = any(
        os.path.isfile(os.path.join(project_root, marker)) for marker in _GRADLE_MARKERS
    )

    timeout = cfg.get("command_timeout_seconds", 300)

    if has_pom:
        mvn = _wrapper(project_root, "mvnw") or find_maven()
        if not mvn:
            return _skipped("pom.xml found but neither mvnw nor a global mvn is available")
        args = cfg.get("java_maven_test_args", "test").split()
        result = await run_command([mvn] + args, cwd=project_root, timeout_seconds=timeout)
        return _result([_stage("mvn-test", result)])

    if has_gradle:
        gradle = _wrapper(project_root, "gradlew") or find_gradle()
        if not gradle:
            return _skipped("build.gradle(.kts) found but neither gradlew nor a global gradle is available")
        args = cfg.get("java_gradle_test_args", "test").split()
        result = await run_command([gradle] + args, cwd=project_root, timeout_seconds=timeout)
        return _result([_stage("gradle-test", result)])

    return _skipped("no pom.xml or build.gradle(.kts) found")


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

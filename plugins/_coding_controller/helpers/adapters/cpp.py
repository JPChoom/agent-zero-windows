"""C/C++ adapter: CMake configure + build, ctest if tests are configured,
clang-format/clang-tidy only if found on PATH (same optional-tool pattern
as powershell.py's PSScriptAnalyzer - missing them skips just that
stage, not the whole gate).

Configures into a dedicated "<project_root>/build" directory rather than
in-source, matching standard CMake practice and keeping generated build
files out of the source tree the diff reviewer looks at.
"""

import os

from plugins._coding_controller.helpers.find_binary import find_executable
from plugins._coding_controller.helpers.process_runner import CommandResult, run_command

_SOURCE_EXTS = (".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx")
_MAX_FORMAT_FILES = 200


def find_cmake() -> str:
    return find_executable(("cmake",))


def find_ctest() -> str:
    return find_executable(("ctest",))


def find_clang_format() -> str:
    return find_executable(("clang-format",))


def find_clang_tidy() -> str:
    return find_executable(("clang-tidy",))


async def run_gate(project_root: str, cfg: dict) -> dict:
    cmake = find_cmake()
    if not cmake:
        return _skipped("cmake not found on PATH; install CMake to enable this gate")

    timeout = cfg.get("command_timeout_seconds", 300)
    stages = []
    build_dir = os.path.join(project_root, "build")

    clang_format = find_clang_format()
    if clang_format:
        files = _source_files(project_root, build_dir)
        if files:
            fmt = await run_command(
                [clang_format, "--dry-run", "--Werror", *files],
                cwd=project_root,
                timeout_seconds=timeout,
            )
            stages.append(_stage("clang-format", fmt))

    configure = await run_command(
        [cmake, "-S", ".", "-B", build_dir, "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"],
        cwd=project_root,
        timeout_seconds=timeout,
    )
    stages.append(_stage("cmake-configure", configure))
    if not configure.passed:
        return _result(stages)

    # --config is required for multi-config generators (Visual Studio,
    # Xcode - CMake's default on Windows) so ctest below can find the
    # built binary; single-config generators (Makefiles, Ninja) ignore it
    # harmlessly, so this one flag works across platforms.
    build = await run_command(
        [cmake, "--build", build_dir, "--config", "Debug"], cwd=project_root, timeout_seconds=timeout
    )
    stages.append(_stage("cmake-build", build))

    clang_tidy = find_clang_tidy()
    compile_db = os.path.join(build_dir, "compile_commands.json")
    if clang_tidy and build.passed and os.path.isfile(compile_db):
        files = _source_files(project_root, build_dir)
        if files:
            tidy = await run_command(
                [clang_tidy, "-p", build_dir, *files], cwd=project_root, timeout_seconds=timeout
            )
            stages.append(_stage("clang-tidy", tidy))

    ctest = find_ctest()
    if ctest and build.passed:
        test = await run_command(
            [ctest, "--test-dir", build_dir, "-C", "Debug", "--output-on-failure"],
            cwd=project_root,
            timeout_seconds=timeout,
        )
        stages.append(_stage("ctest", test))

    return _result(stages)


def _source_files(project_root: str, build_dir: str) -> list[str]:
    files = []
    for root, dirs, names in os.walk(project_root):
        # Never descend into the CMake build directory (generated files,
        # potentially huge) or version control metadata.
        dirs[:] = [d for d in dirs if d not in (".git", "build", os.path.basename(build_dir))]
        for name in names:
            if name.lower().endswith(_SOURCE_EXTS):
                files.append(os.path.relpath(os.path.join(root, name), project_root))
                if len(files) >= _MAX_FORMAT_FILES:
                    return files
    return files


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

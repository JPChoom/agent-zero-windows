"""Git status/diff helpers for the independent reviewer and (later,
in-progress work) user-change protection.

Reuses process_runner.run_command - same authoritative-exit-code
subprocess execution the quality-gate adapters use, not the interactive
terminal. All functions degrade gracefully (empty result, not an
exception) when the project root isn't a git repository or git isn't on
PATH - a coding task should still be reviewable without git, just with
less evidence available.
"""

from plugins._coding_controller.helpers.process_runner import run_command
from plugins._coding_controller.helpers.find_binary import find_executable

_WINDOWS_GIT_CANDIDATES = (r"C:\Program Files\Git\cmd\git.exe",)


def find_git() -> str:
    return find_executable(("git",), _WINDOWS_GIT_CANDIDATES)


async def get_git_status(project_root: str, timeout_seconds: int = 30) -> str:
    """`git status --short` output, or "" if git/repo unavailable."""
    git = find_git()
    if not git:
        return ""
    result = await run_command(
        [git, "status", "--short"], cwd=project_root, timeout_seconds=timeout_seconds
    )
    return result.stdout if result.passed else ""


async def get_git_diff(
    project_root: str, path: str | None = None, timeout_seconds: int = 30
) -> str:
    """`git diff` (working tree vs. HEAD) for the whole repo or one path."""
    git = find_git()
    if not git:
        return ""
    args = [git, "diff"]
    if path:
        args += ["--", path]
    result = await run_command(args, cwd=project_root, timeout_seconds=timeout_seconds)
    return result.stdout if result.passed else ""


async def get_changed_files(project_root: str, timeout_seconds: int = 30) -> list[str]:
    """Paths (relative to project_root) with any working-tree change,
    staged or not - parsed from `git status --short`'s porcelain format."""
    status = await get_git_status(project_root, timeout_seconds=timeout_seconds)
    files: list[str] = []
    for line in status.splitlines():
        if len(line) <= 3:
            continue
        # Porcelain short format: "XY path" or "XY orig -> path" for renames.
        path_part = line[3:].strip()
        if " -> " in path_part:
            path_part = path_part.split(" -> ", 1)[1]
        if path_part:
            files.append(path_part)
    return files


async def is_git_repo(project_root: str, timeout_seconds: int = 30) -> bool:
    git = find_git()
    if not git:
        return False
    result = await run_command(
        [git, "rev-parse", "--is-inside-work-tree"],
        cwd=project_root,
        timeout_seconds=timeout_seconds,
    )
    return result.passed and result.stdout.strip().lower() == "true"

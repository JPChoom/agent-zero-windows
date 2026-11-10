"""A git worktree per coding task: its own branch and folder.

A task's changes stay apart from the main checkout until they are reviewed:
`start` makes branch `a0/<name>` and a folder for it (git worktree), the
agent works there, `diff` shows everything the task changed, `commit` saves
it on the task branch, `merge` brings it into the branch it started from
(fast-forward only, so nothing is merged blindly), `discard` removes both.

Folders go under the workdir (`<workdir>/.worktrees/<repo>-<name>`), where
the agent's file tools can reach them. Commits and merges are ordinary tool
calls, so the permission mode applies (Manual asks first) and capability
policies can refuse them (`coding_task:merge`).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from plugins._coding_controller.helpers.git_state import find_git
from plugins._coding_controller.helpers.process_runner import run_command

REGISTRY_KEY = "coding_tasks"  # chat data, saved: {name: {repo, path, branch, base}}
BRANCH_PREFIX = "a0/"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
MAX_DIFF_CHARS = 20000
TIMEOUT = 60


class TaskError(ValueError):
    pass


async def _git(cwd: str, *args: str) -> str:
    git = find_git()
    if not git:
        raise TaskError("git is not installed or not on PATH.")
    result = await run_command([git, *args], cwd=cwd, timeout_seconds=TIMEOUT, enable_process_broker=False)
    if not result.passed:
        raise TaskError(f"git {' '.join(args[:2])} failed: {(result.stderr or result.stdout).strip()[:500]}")
    return result.stdout


def _name(value: Any) -> str:
    name = str(value or "").strip().lower().replace(" ", "-")
    if not NAME_RE.match(name):
        raise TaskError("A task needs a short name: letters, digits, - or _ (for example fix-parser).")
    return name


def _workdir() -> Path:
    from plugins._text_editor.helpers.file_ops import get_workdir_root

    return get_workdir_root()


def registry(context) -> dict[str, dict]:
    value = context.get_data(REGISTRY_KEY)
    return dict(value) if isinstance(value, dict) else {}


def _task(context, name: str) -> dict:
    task = registry(context).get(_name(name))
    if not task:
        raise TaskError(f"No coding task called '{name}' in this chat. Start one first.")
    return task


async def start(context, repo: str, name: str, base: str = "") -> dict:
    from helpers import files

    name = _name(name)
    if name in registry(context):
        raise TaskError(f"Task '{name}' already exists: {registry(context)[name]['path']}")
    repo_path = files.native_path(str(repo or "").strip())
    if not repo_path or not Path(repo_path).is_dir():
        raise TaskError("repo must be the folder of a git repository.")
    top = (await _git(repo_path, "rev-parse", "--show-toplevel")).strip()
    base_ref = base.strip() or (await _git(top, "rev-parse", "--abbrev-ref", "HEAD")).strip()
    base_commit = (await _git(top, "rev-parse", base_ref)).strip()
    folder = _workdir() / ".worktrees" / f"{Path(top).name}-{name}"
    if folder.exists():
        raise TaskError(f"{folder} already exists; discard the old task or pick another name.")
    branch = BRANCH_PREFIX + name
    await _git(top, "worktree", "add", "-b", branch, str(folder), base_commit)
    task = {"repo": top, "path": str(folder), "branch": branch, "base": base_ref, "base_commit": base_commit}
    tasks = registry(context)
    tasks[name] = task
    context.set_data(REGISTRY_KEY, tasks)
    return {"name": name, **task}


async def diff(context, name: str) -> dict:
    task = _task(context, name)
    stat = await _git(task["path"], "diff", "--stat", task["base_commit"])
    untracked = await _git(task["path"], "ls-files", "--others", "--exclude-standard")
    patch = await _git(task["path"], "diff", task["base_commit"])
    if len(patch) > MAX_DIFF_CHARS:
        patch = patch[:MAX_DIFF_CHARS] + f"\n... ({len(patch) - MAX_DIFF_CHARS} more characters)"
    return {"name": _name(name), "path": task["path"], "stat": stat.strip(),
            "new_files": untracked.split(), "diff": patch}


async def commit(context, name: str, message: str) -> dict:
    task = _task(context, name)
    if not str(message or "").strip():
        raise TaskError("A commit needs a message.")
    await _git(task["path"], "add", "-A")
    status = await _git(task["path"], "status", "--porcelain")
    if not status.strip():
        return {"name": _name(name), "committed": False, "note": "nothing to commit"}
    await _git(task["path"], "commit", "-m", message)
    head = (await _git(task["path"], "rev-parse", "--short", "HEAD")).strip()
    return {"name": _name(name), "committed": True, "commit": head, "branch": task["branch"]}


async def merge(context, name: str, keep: bool = False) -> dict:
    """Fast-forward the starting branch to the task branch, in the main checkout,
    then remove the task's worktree and its merged branch (a finished task
    leaves nothing behind) unless `keep` is set."""
    task = _task(context, name)
    pending = await _git(task["path"], "status", "--porcelain")
    if pending.strip():
        raise TaskError("The task has uncommitted changes. Commit them first.")
    current = (await _git(task["repo"], "rev-parse", "--abbrev-ref", "HEAD")).strip()
    if current != task["base"]:
        raise TaskError(f"The main checkout is on '{current}', not '{task['base']}'; switch it back before merging.")
    dirty = await _git(task["repo"], "status", "--porcelain", "--untracked-files=no")
    if dirty.strip():
        raise TaskError("The main checkout has uncommitted changes; merging now could mix them in.")
    try:
        await _git(task["repo"], "merge", "--ff-only", task["branch"])
    except TaskError as exc:
        raise TaskError(f"'{task['base']}' moved on since the task started; rebase the task branch onto it first. ({exc})") from exc
    outcome = {"name": _name(name), "merged": True, "into": task["base"]}
    if keep:
        return {**outcome, "kept": task["path"]}
    try:
        await _git(task["repo"], "worktree", "remove", task["path"])
        await _git(task["repo"], "branch", "-d", task["branch"])  # merged, so -d is safe
    except TaskError as exc:
        return {**outcome, "cleanup": f"merged, but the worktree or branch could not be removed: {exc}; use discard"}
    tasks = registry(context)
    tasks.pop(_name(name), None)
    context.set_data(REGISTRY_KEY, tasks)
    return {**outcome, "cleaned_up": True}


async def discard(context, name: str) -> dict:
    task = _task(context, name)
    await _git(task["repo"], "worktree", "remove", "--force", task["path"])
    try:
        await _git(task["repo"], "branch", "-D", task["branch"])
    except TaskError:
        pass  # already gone
    tasks = registry(context)
    tasks.pop(_name(name), None)
    context.set_data(REGISTRY_KEY, tasks)
    return {"name": _name(name), "discarded": True}


def describe(context) -> list[dict]:
    return [{"name": name, **task} for name, task in registry(context).items()]

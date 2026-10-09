"""Update a native Windows install (a git clone) to a published release of
Agent Zero for Windows.

Check: the latest GitHub release of RELEASE_REPO (no identifiers are sent).
Apply: fetch that release tag and fast-forward the checkout to it, installing
requirements.txt when the release changed it. It never discards work: it
refuses when tracked files are modified, the checkout is not on `main`, or
the checkout has commits the release does not contain. The previous commit is
kept in usr/ so the update can be rolled back. The new code runs after a
restart (`helpers/process.reload`).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from helpers import files

RELEASE_REPO = "JPChoom/agent-zero-windows"
RELEASE_GIT_URL = f"https://github.com/{RELEASE_REPO}.git"
RELEASE_API_URL = f"https://api.github.com/repos/{RELEASE_REPO}/releases/latest"
STATE_FILE = "usr/windows_update.json"
RELEASE_CACHE_SECONDS = 60 * 60
UPDATE_BRANCH = "main"
TAG_PATTERN = re.compile(r"^v\d+(\.\d+){1,2}$")

_release_cache: tuple[float, dict | None] | None = None
_apply_lock = threading.Lock()


class UpdateError(Exception):
    pass


# ------------------------------------------------------------------ helpers

def _repo_dir() -> str:
    return files.get_base_dir()


def _git(*args: str, timeout: int = 120) -> str:
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    result = subprocess.run(
        ["git", *args], cwd=_repo_dir(), capture_output=True, text=True,
        timeout=timeout, encoding="utf-8", errors="replace", **kwargs,
    )
    if result.returncode != 0:
        raise UpdateError(f"git {' '.join(args)} failed: {(result.stderr or result.stdout).strip()}")
    # rstrip only: `status --porcelain` lines start with a significant space.
    return result.stdout.rstrip()


def _git_ok(*args: str) -> bool:
    try:
        _git(*args)
        return True
    except UpdateError:
        return False


def parse_version(tag: str) -> tuple[int, ...] | None:
    if not tag or not TAG_PATTERN.match(tag.strip()):
        return None
    parts = tuple(int(p) for p in tag.strip()[1:].split("."))
    return parts + (0,) * (3 - len(parts))


def is_newer(candidate: str, current: str) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    return a is not None and b is not None and a > b


def _state_path() -> Path:
    return Path(files.get_abs_path(STATE_FILE))


def load_state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _process_started_at() -> float:
    try:
        import psutil

        return psutil.Process(os.getpid()).create_time()
    except Exception:
        return 0.0


# ------------------------------------------------------------------ local state

def local_info() -> dict:
    """Version and readiness of this checkout. `blockers` lists every reason
    an update cannot be applied safely."""
    info: dict = {"is_git": False, "blockers": []}
    if not _git_ok("rev-parse", "--is-inside-work-tree"):
        info["blockers"].append("This install is not a git checkout, so it cannot update itself.")
        return info
    info["is_git"] = True
    info["head"] = _git("rev-parse", "HEAD")
    info["branch"] = _git("rev-parse", "--abbrev-ref", "HEAD")
    try:
        info["describe"] = _git("describe", "--tags")
        info["version"] = _git("describe", "--tags", "--abbrev=0")
    except UpdateError:
        info["describe"] = info["version"] = ""
    modified = [line[3:] for line in _git("status", "--porcelain", "--untracked-files=no").splitlines() if line.strip()]
    info["modified_files"] = modified
    if info["branch"] != UPDATE_BRANCH:
        info["blockers"].append(f"The checkout is on '{info['branch']}', not '{UPDATE_BRANCH}'.")
    if modified:
        info["blockers"].append(
            f"{len(modified)} tracked file(s) are modified; commit or undo them first: " + ", ".join(modified[:5])
        )
    return info


# ------------------------------------------------------------------ release check

async def fetch_latest_release(force: bool = False) -> dict | None:
    global _release_cache
    now = time.monotonic()
    if not force and _release_cache and now - _release_cache[0] < RELEASE_CACHE_SECONDS:
        return _release_cache[1]
    import httpx

    release = None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(RELEASE_API_URL, headers={"Accept": "application/vnd.github+json"})
        if response.status_code == 200:
            data = response.json()
            if parse_version(str(data.get("tag_name") or "")) and not data.get("draft") and not data.get("prerelease"):
                release = {
                    "tag": data["tag_name"],
                    "name": data.get("name") or data["tag_name"],
                    "notes": (data.get("body") or "")[:20000],
                    "url": data.get("html_url") or "",
                    "published_at": data.get("published_at") or "",
                }
    except Exception:
        release = None
    _release_cache = (now, release)
    return release


async def check(force: bool = False) -> dict:
    local = local_info()
    release = await fetch_latest_release(force=force)
    state = load_state()
    current = local.get("version", "")
    available = bool(release and is_newer(release["tag"], current))
    result = {
        "repo": RELEASE_REPO,
        "current_version": current,
        "current_describe": local.get("describe", ""),
        "latest": release,
        "check_failed": release is None,
        "update_available": available,
        "blockers": list(local["blockers"]),
        "can_apply": available and not local["blockers"],
        "restart_pending": bool(state.get("applied_at_epoch", 0) > _process_started_at()),
        "rollback": (
            {"to_version": state.get("previous_version", ""), "to_head": state.get("previous_head", "")}
            if state.get("previous_head") else None
        ),
        "last_update": state or None,
    }
    if local.get("describe") and local.get("describe") != current:
        result["note"] = (
            f"This copy is ahead of {current} ({local['describe']}): it has commits that are not in a release."
        )
    return result


# ------------------------------------------------------------------ apply / rollback

def _fetch_tag(tag: str) -> None:
    _git("fetch", "--no-tags", RELEASE_GIT_URL, f"+refs/tags/{tag}:refs/tags/{tag}", timeout=300)


def _install_requirements() -> None:
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-cache-dir", "-r", "requirements.txt"],
        cwd=_repo_dir(), capture_output=True, text=True, timeout=1800,
        encoding="utf-8", errors="replace", **kwargs,
    )
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip()[-1500:]
        raise UpdateError(f"Installing the release's requirements failed:\n{tail}")


def apply(tag: str) -> dict:
    """Fast-forward this checkout to release `tag`. Restart required afterwards."""
    if not parse_version(tag):
        raise UpdateError(f"Not a release tag: {tag!r}")
    if not _apply_lock.acquire(blocking=False):
        raise UpdateError("An update is already running.")
    try:
        local = local_info()
        if local["blockers"]:
            raise UpdateError(" ".join(local["blockers"]))
        _fetch_tag(tag)
        if not _git_ok("merge-base", "--is-ancestor", "HEAD", tag):
            raise UpdateError(
                f"This copy has commits that {tag} does not contain, so it cannot be fast-forwarded."
            )
        previous_head = local["head"]
        requirements_changed = not _git_ok("diff", "--quiet", previous_head, tag, "--", "requirements.txt")
        _git("merge", "--ff-only", tag)
        if requirements_changed:
            try:
                _install_requirements()
            except UpdateError:
                _git("reset", "--keep", previous_head)
                raise
        now = datetime.now(timezone.utc)
        state = {
            "previous_head": previous_head,
            "previous_version": local.get("describe") or local.get("version", ""),
            "updated_to": tag,
            "requirements_installed": requirements_changed,
            "applied_at": now.isoformat(),
            "applied_at_epoch": time.time(),
        }
        _save_state(state)
        return {"ok": True, "updated_to": tag, "requirements_installed": requirements_changed, "restart_required": True}
    finally:
        _apply_lock.release()


def rollback() -> dict:
    """Return the checkout to the commit it was on before the last update."""
    state = load_state()
    previous = state.get("previous_head", "")
    if not previous:
        raise UpdateError("There is no earlier version to roll back to.")
    if not _apply_lock.acquire(blocking=False):
        raise UpdateError("An update is already running.")
    try:
        local = local_info()
        if local.get("modified_files"):
            raise UpdateError("Tracked files are modified; commit or undo them before rolling back.")
        requirements_changed = not _git_ok("diff", "--quiet", "HEAD", previous, "--", "requirements.txt")
        _git("reset", "--keep", previous)
        if requirements_changed:
            _install_requirements()
        _save_state({
            "rolled_back_from": state.get("updated_to", ""),
            "rolled_back_to": state.get("previous_version", ""),
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "applied_at_epoch": time.time(),
        })
        return {"ok": True, "rolled_back_to": state.get("previous_version", ""), "restart_required": True}
    finally:
        _apply_lock.release()

"""A git worktree per coding task, with real git."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from plugins._coding_controller.helpers import task_worktrees as tw

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


class _Context:
    def __init__(self):
        self.data = {}

    def get_data(self, key):
        return self.data.get(key)

    def set_data(self, key, value):
        self.data[key] = value


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "workdir" / "myapp"
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "app.py").write_text("print('v1')\n", encoding="utf-8")
    _git(root, "add", "app.py")
    _git(root, "commit", "-q", "-m", "first")
    monkeypatch.setattr(tw, "_workdir", lambda: tmp_path / "workdir")
    return root


def _run(coro):
    return asyncio.run(coro)


def test_a_task_gets_its_own_branch_and_folder(repo):
    context = _Context()
    task = _run(tw.start(context, str(repo), "fix-parser"))
    folder = Path(task["path"])
    assert folder.is_dir() and folder.parent.name == ".worktrees" and task["branch"] == "a0/fix-parser"
    assert task["base"] == "main" and (folder / "app.py").is_file()
    assert tw.describe(context)[0]["name"] == "fix-parser"


def test_the_whole_lifecycle_lands_only_on_merge(repo):
    context = _Context()
    folder = Path(_run(tw.start(context, str(repo), "feature"))["path"])
    (folder / "app.py").write_text("print('v2')\n", encoding="utf-8")
    (folder / "new.py").write_text("x = 1\n", encoding="utf-8")
    changes = _run(tw.diff(context, "feature"))
    assert "v2" in changes["diff"] and "new.py" in changes["new_files"]
    assert (repo / "app.py").read_text(encoding="utf-8") == "print('v1')\n"  # the main checkout is untouched
    assert _run(tw.commit(context, "feature", "Change v2"))["committed"]
    assert _run(tw.merge(context, "feature"))["merged"]
    assert (repo / "app.py").read_text(encoding="utf-8") == "print('v2')\n" and (repo / "new.py").is_file()
    _run(tw.discard(context, "feature"))
    assert not folder.exists() and "a0/feature" not in _git(repo, "branch")
    assert tw.describe(context) == []


def test_merge_refuses_uncommitted_work(repo):
    context = _Context()
    folder = Path(_run(tw.start(context, str(repo), "wip"))["path"])
    (folder / "app.py").write_text("print('wip')\n", encoding="utf-8")
    with pytest.raises(tw.TaskError, match="uncommitted"):
        _run(tw.merge(context, "wip"))


def test_merge_refuses_when_the_base_moved_on(repo):
    context = _Context()
    folder = Path(_run(tw.start(context, str(repo), "late"))["path"])
    (folder / "app.py").write_text("print('task')\n", encoding="utf-8")
    _run(tw.commit(context, "late", "task change"))
    (repo / "other.py").write_text("y = 2\n", encoding="utf-8")
    _git(repo, "add", "other.py")
    _git(repo, "commit", "-q", "-m", "someone else")
    with pytest.raises(tw.TaskError, match="moved on"):
        _run(tw.merge(context, "late"))
    assert (repo / "app.py").read_text(encoding="utf-8") == "print('v1')\n"


def test_merge_refuses_a_dirty_main_checkout(repo):
    context = _Context()
    folder = Path(_run(tw.start(context, str(repo), "clean"))["path"])
    (folder / "app.py").write_text("print('task')\n", encoding="utf-8")
    _run(tw.commit(context, "clean", "task"))
    (repo / "app.py").write_text("print('user editing')\n", encoding="utf-8")
    with pytest.raises(tw.TaskError, match="uncommitted changes"):
        _run(tw.merge(context, "clean"))
    assert (repo / "app.py").read_text(encoding="utf-8") == "print('user editing')\n"


@pytest.mark.parametrize("name", ["bad name!", "", "../escape"])
def test_bad_names_are_refused(repo, name):
    with pytest.raises(tw.TaskError, match="short name"):
        _run(tw.start(_Context(), str(repo), name))


def test_not_a_repo_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(tw, "_workdir", lambda: tmp_path)
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(tw.TaskError):
        _run(tw.start(_Context(), str(plain), "x"))


def test_unknown_tasks_and_empty_commits(repo):
    context = _Context()
    with pytest.raises(tw.TaskError, match="No coding task"):
        _run(tw.diff(context, "nothing"))
    _run(tw.start(context, str(repo), "idle"))
    assert _run(tw.commit(context, "idle", "nothing yet"))["committed"] is False
    with pytest.raises(tw.TaskError, match="needs a message"):
        _run(tw.commit(context, "idle", ""))

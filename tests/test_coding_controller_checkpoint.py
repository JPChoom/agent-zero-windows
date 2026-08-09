"""Tests for checkpoint.py: repair-attempt file snapshotting, worsening
detection, and rollback (Phase C of the hand-off roadmap). Uses real git
repos in tmp_path, same pattern as test_coding_controller_reviewer.py's
git_state tests.
"""

import subprocess

import pytest

from plugins._coding_controller.helpers import checkpoint


def _init_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


def _commit_all(path, message="initial"):
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=path, check=True)


# ------------------------------------------------------------------
# save_checkpoint / restore_checkpoint
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_checkpoint_on_non_git_dir_is_a_noop(tmp_path):
    cp = await checkpoint.save_checkpoint(str(tmp_path), {"build": frozenset({"x"})})

    assert cp.is_git_repo is False
    assert cp.file_snapshots == {}
    assert cp.fingerprint == {"build": frozenset({"x"})}


@pytest.mark.asyncio
async def test_save_checkpoint_captures_modified_tracked_file(tmp_path):
    _init_repo(tmp_path)
    target = tmp_path / "a.txt"
    target.write_text("original\n", encoding="utf-8", newline="")
    _commit_all(tmp_path)

    target.write_text("modified\n", encoding="utf-8", newline="")

    cp = await checkpoint.save_checkpoint(str(tmp_path), {})

    assert cp.is_git_repo is True
    assert cp.file_snapshots["a.txt"] == b"modified\n"


@pytest.mark.asyncio
async def test_save_checkpoint_records_new_untracked_file(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "base.txt").write_text("base\n", encoding="utf-8", newline="")
    _commit_all(tmp_path)

    (tmp_path / "new.txt").write_text("brand new\n", encoding="utf-8", newline="")

    cp = await checkpoint.save_checkpoint(str(tmp_path), {})

    assert cp.file_snapshots["new.txt"] == b"brand new\n"


@pytest.mark.asyncio
async def test_restore_checkpoint_reverts_modified_content(tmp_path):
    _init_repo(tmp_path)
    target = tmp_path / "a.txt"
    target.write_text("original\n", encoding="utf-8", newline="")
    _commit_all(tmp_path)

    target.write_text("attempt 1\n", encoding="utf-8", newline="")
    cp = await checkpoint.save_checkpoint(str(tmp_path), {})

    target.write_text("attempt 2 - made it worse\n", encoding="utf-8", newline="")

    await checkpoint.restore_checkpoint(cp)

    assert target.read_text(encoding="utf-8") == "attempt 1\n"


@pytest.mark.asyncio
async def test_restore_checkpoint_removes_file_that_did_not_exist_at_snapshot_time(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "base.txt").write_text("base\n", encoding="utf-8", newline="")
    _commit_all(tmp_path)

    # No changes yet at checkpoint time.
    cp = await checkpoint.save_checkpoint(str(tmp_path), {})
    assert cp.file_snapshots == {}

    # A later attempt creates a file that wasn't there at checkpoint time.
    created = tmp_path / "created_by_attempt.txt"
    created.write_text("oops\n", encoding="utf-8", newline="")

    await checkpoint.restore_checkpoint(cp)

    assert not created.exists()


@pytest.mark.asyncio
async def test_restore_checkpoint_removes_file_created_after_checkpoint_not_in_snapshot(tmp_path):
    _init_repo(tmp_path)
    target = tmp_path / "a.txt"
    target.write_text("original\n", encoding="utf-8", newline="")
    _commit_all(tmp_path)

    target.write_text("attempt 1\n", encoding="utf-8", newline="")
    cp = await checkpoint.save_checkpoint(str(tmp_path), {})
    assert "b.txt" not in cp.file_snapshots

    # Attempt 2 modifies a.txt further AND creates a wholly new file.
    target.write_text("attempt 2\n", encoding="utf-8", newline="")
    extra = tmp_path / "b.txt"
    extra.write_text("side effect of attempt 2\n", encoding="utf-8", newline="")

    await checkpoint.restore_checkpoint(cp)

    assert target.read_text(encoding="utf-8") == "attempt 1\n"
    assert not extra.exists()


@pytest.mark.asyncio
async def test_restore_checkpoint_on_non_git_checkpoint_is_a_noop(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("untouched\n", encoding="utf-8", newline="")

    cp = checkpoint.Checkpoint(root=str(tmp_path), is_git_repo=False, fingerprint={})
    await checkpoint.restore_checkpoint(cp)  # must not raise or touch anything

    assert target.read_text(encoding="utf-8") == "untouched\n"


# ------------------------------------------------------------------
# is_worse
# ------------------------------------------------------------------

def test_is_worse_true_when_previously_passing_stage_now_fails():
    current = {"build": frozenset({"x"}), "test": frozenset({"y"})}
    checkpoint_fp = {"build": frozenset({"x"})}

    assert checkpoint.is_worse(current, checkpoint_fp) is True


def test_is_worse_true_when_strictly_more_findings():
    current = {"build": frozenset({"x", "y"})}
    checkpoint_fp = {"build": frozenset({"x"})}

    assert checkpoint.is_worse(current, checkpoint_fp) is True


def test_is_worse_false_when_findings_improve():
    current = {"build": frozenset({"x"})}
    checkpoint_fp = {"build": frozenset({"x", "y"})}

    assert checkpoint.is_worse(current, checkpoint_fp) is False


def test_is_worse_false_when_unchanged():
    current = {"build": frozenset({"x"})}
    checkpoint_fp = {"build": frozenset({"x"})}

    assert checkpoint.is_worse(current, checkpoint_fp) is False


def test_is_worse_false_when_both_empty():
    assert checkpoint.is_worse({}, {}) is False


# ------------------------------------------------------------------
# _resolve path traversal protection
# ------------------------------------------------------------------

def test_resolve_rejects_path_escaping_root(tmp_path):
    assert checkpoint._resolve(str(tmp_path), "../../etc/passwd") is None


def test_resolve_accepts_path_inside_root(tmp_path):
    resolved = checkpoint._resolve(str(tmp_path), "sub/file.txt")

    assert resolved is not None
    assert str(resolved).startswith(str(tmp_path))

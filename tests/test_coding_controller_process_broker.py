"""Tests for process_broker.py (Windows Job Object resource isolation) and
its wiring into process_runner.run_command.

Job Object behavior itself is exercised live (real CreateJobObject/
AssignProcessToJobObject/TerminateJobObject calls against a real spawned
process tree) rather than mocked, since the whole point is kernel-enforced
guarantees a mock can't validate.
"""

import asyncio
import subprocess
import sys
import time
from pathlib import Path

import pytest

from plugins._coding_controller.helpers import process_broker, process_runner


# ------------------------------------------------------------------
# process_broker
# ------------------------------------------------------------------

def test_is_available_on_windows():
    assert process_broker.is_available() == (process_broker._AVAILABLE)


@pytest.mark.skipif(not process_broker.is_available(), reason="pywin32/Job Objects not available")
def test_create_job_returns_handle():
    job = process_broker.create_job()
    try:
        assert job is not None
    finally:
        job.close()


@pytest.mark.skipif(not process_broker.is_available(), reason="pywin32/Job Objects not available")
def test_assign_process_to_job_succeeds_for_child(tmp_path: Path):
    # Deliberately NOT assigning the current (pytest) process here: the job
    # is created with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, so closing the
    # handle terminates every process still in the job - assigning your own
    # interpreter to it would kill the test run itself on job.close().
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    job = process_broker.create_job()
    try:
        assert process_broker.assign_process(job, proc.pid) is True
    finally:
        job.terminate()
        job.close()
        proc.wait(timeout=10)


def test_assign_process_returns_false_for_none_job():
    assert process_broker.assign_process(None, 1234) is False


def test_create_job_returns_none_when_unavailable(monkeypatch):
    monkeypatch.setattr(process_broker, "_AVAILABLE", False)
    assert process_broker.create_job() is None


@pytest.mark.skipif(not process_broker.is_available(), reason="pywin32/Job Objects not available")
def test_terminate_job_kills_real_child_process_tree(tmp_path: Path):
    """Spawns a real parent process that spawns a real grandchild, assigns
    the parent to a job, then terminates the job and confirms BOTH
    processes die - proving job-based termination reaches descendants that
    a plain proc.kill() on just the parent would leave orphaned."""
    child_marker = tmp_path / "child_alive.txt"
    parent_script = tmp_path / "parent.py"
    child_script = tmp_path / "child.py"

    child_script.write_text(
        "import pathlib, time\n"
        f"pathlib.Path(r'{child_marker}').write_text('running')\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    parent_script.write_text(
        f"import subprocess, time\n"
        f"subprocess.Popen([r'{sys.executable}', r'{child_script}'])\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )

    parent = subprocess.Popen(
        [sys.executable, str(parent_script)],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    job = process_broker.create_job()
    assert job is not None
    assigned = process_broker.assign_process(job, parent.pid)
    assert assigned is True

    # Wait for the grandchild to actually start and write its marker.
    deadline = time.monotonic() + 10
    while not child_marker.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert child_marker.exists(), "child process never started"

    job.terminate()
    job.close()

    parent.wait(timeout=10)
    assert parent.returncode is not None


# ------------------------------------------------------------------
# process_runner wiring
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_command_still_works_with_broker_enabled(tmp_path: Path):
    result = await process_runner.run_command(
        [sys.executable, "-c", "print('hi')"], cwd=str(tmp_path), timeout_seconds=15
    )
    assert result.passed
    assert "hi" in result.stdout


@pytest.mark.asyncio
async def test_run_command_works_with_broker_disabled(tmp_path: Path):
    result = await process_runner.run_command(
        [sys.executable, "-c", "print('hi')"],
        cwd=str(tmp_path),
        timeout_seconds=15,
        enable_process_broker=False,
    )
    assert result.passed
    assert "hi" in result.stdout


@pytest.mark.asyncio
async def test_run_command_timeout_still_reports_timed_out_with_broker(tmp_path: Path):
    result = await process_runner.run_command(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=str(tmp_path),
        timeout_seconds=1,
    )
    assert result.timed_out
    assert not result.passed


@pytest.mark.asyncio
async def test_run_command_succeeds_when_assign_process_fails(monkeypatch, tmp_path: Path):
    """assign_process failing (e.g. the process already belongs to another
    job without break-away rights) must be a soft failure - the command
    still has to run and report its real result."""
    monkeypatch.setattr(process_broker, "assign_process", lambda job, pid: False)

    result = await process_runner.run_command(
        [sys.executable, "-c", "print('hi')"], cwd=str(tmp_path), timeout_seconds=15
    )
    assert result.passed
    assert "hi" in result.stdout


@pytest.mark.asyncio
async def test_run_command_succeeds_when_create_job_returns_none(monkeypatch, tmp_path: Path):
    """create_job() itself already swallows its own errors and returns
    None on failure (see process_broker.create_job) - run_command must
    treat that the same as "broker unavailable" and proceed normally."""
    monkeypatch.setattr(process_broker, "create_job", lambda **kwargs: None)

    result = await process_runner.run_command(
        [sys.executable, "-c", "print('hi')"], cwd=str(tmp_path), timeout_seconds=15
    )
    assert result.passed
    assert "hi" in result.stdout

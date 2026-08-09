"""Tests for the _coding_controller plugin: project detection, dirty/repair
state tracking, subprocess execution (incl. the Windows .cmd wrapper fix),
dotnet diagnostic parsing, and gate orchestration.
"""

import asyncio
from pathlib import Path

import pytest

from plugins._coding_controller.helpers import (
    diagnostics,
    gate_controller,
    process_runner,
    project_detector,
    session_state,
)


# ------------------------------------------------------------------
# project_detector
# ------------------------------------------------------------------

def test_detect_dotnet_via_sln(tmp_path: Path):
    (tmp_path / "MyApp.sln").write_text("", encoding="utf-8")
    sub = tmp_path / "src"
    sub.mkdir()

    info = project_detector.detect_project(str(sub))

    assert info is not None
    assert info.kind == "dotnet"
    assert info.root == str(tmp_path)
    assert info.marker == "MyApp.sln"


def test_detect_dotnet_via_csproj_without_sln(tmp_path: Path):
    (tmp_path / "MyApp.csproj").write_text("", encoding="utf-8")

    info = project_detector.detect_project(str(tmp_path))

    assert info is not None
    assert info.kind == "dotnet"
    assert info.root == str(tmp_path)


def test_detect_npm_via_package_json(tmp_path: Path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    nested = tmp_path / "src" / "components"
    nested.mkdir(parents=True)

    info = project_detector.detect_project(str(nested))

    assert info is not None
    assert info.kind == "npm"
    assert info.root == str(tmp_path)


def test_detect_powershell_standalone_script(tmp_path: Path):
    script = tmp_path / "deploy.ps1"
    script.write_text("Write-Host 'hi'", encoding="utf-8")

    info = project_detector.detect_project(str(script))

    assert info is not None
    assert info.kind == "powershell"
    assert info.root == str(tmp_path)
    assert info.marker == "deploy.ps1"


def test_detect_none_for_unrelated_folder(tmp_path: Path):
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")

    info = project_detector.detect_project(str(tmp_path))

    assert info is None


def test_dotnet_takes_priority_over_npm_at_same_level(tmp_path: Path):
    (tmp_path / "MyApp.csproj").write_text("", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")

    info = project_detector.detect_project(str(tmp_path))

    assert info is not None
    assert info.kind == "dotnet"


# ------------------------------------------------------------------
# session_state
# ------------------------------------------------------------------

class _FakeAgent:
    def __init__(self):
        self.data: dict = {}


def test_mark_dirty_for_path_records_project_root(tmp_path: Path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    file_path = tmp_path / "index.js"
    file_path.write_text("", encoding="utf-8")
    agent = _FakeAgent()

    session_state.mark_dirty_for_path(agent, str(file_path))

    dirty = session_state.get_dirty_roots(agent)
    assert dirty == {str(tmp_path): "npm"}


def test_mark_dirty_for_path_noop_when_no_project_detected(tmp_path: Path):
    file_path = tmp_path / "notes.txt"
    file_path.write_text("", encoding="utf-8")
    agent = _FakeAgent()

    session_state.mark_dirty_for_path(agent, str(file_path))

    assert session_state.get_dirty_roots(agent) == {}


def test_clear_dirty_removes_root(tmp_path: Path):
    agent = _FakeAgent()
    agent.data[session_state.DIRTY_ROOTS_KEY] = {str(tmp_path): "dotnet"}

    session_state.clear_dirty(agent, str(tmp_path))

    assert session_state.get_dirty_roots(agent) == {}


def test_repair_attempts_increment_and_survive_further_edits(tmp_path: Path):
    (tmp_path / "MyApp.csproj").write_text("", encoding="utf-8")
    file_path = tmp_path / "Program.cs"
    file_path.write_text("", encoding="utf-8")
    agent = _FakeAgent()

    assert session_state.get_repair_attempts(agent, str(tmp_path)) == 0
    assert session_state.increment_repair_attempts(agent, str(tmp_path)) == 1
    assert session_state.increment_repair_attempts(agent, str(tmp_path)) == 2
    assert session_state.get_repair_attempts(agent, str(tmp_path)) == 2

    # A repair attempt inherently involves editing the file again - the
    # counter must survive that edit, otherwise max_repair_attempts would
    # never actually trigger in real usage (every attempt would reset it).
    session_state.mark_dirty_for_path(agent, str(file_path))
    assert session_state.get_repair_attempts(agent, str(tmp_path)) == 2


def test_clear_dirty_resets_repair_attempts(tmp_path: Path):
    agent = _FakeAgent()
    agent.data[session_state.DIRTY_ROOTS_KEY] = {str(tmp_path): "dotnet"}
    session_state.increment_repair_attempts(agent, str(tmp_path))
    session_state.increment_repair_attempts(agent, str(tmp_path))

    session_state.clear_dirty(agent, str(tmp_path))

    assert session_state.get_dirty_roots(agent) == {}
    assert session_state.get_repair_attempts(agent, str(tmp_path)) == 0


def test_baseline_defaults_to_none(tmp_path: Path):
    agent = _FakeAgent()

    assert session_state.get_baseline(agent, str(tmp_path)) is None


def test_set_and_get_baseline(tmp_path: Path):
    agent = _FakeAgent()
    baseline = {"build": frozenset({("A.cs", "CS1", "boom")})}

    session_state.set_baseline(agent, str(tmp_path), baseline)

    assert session_state.get_baseline(agent, str(tmp_path)) == baseline


# ------------------------------------------------------------------
# process_runner
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_command_success(tmp_path: Path):
    import sys

    result = await process_runner.run_command(
        [sys.executable, "-c", "print('hello')"], cwd=str(tmp_path), timeout_seconds=15
    )

    assert result.passed
    assert result.exit_code == 0
    assert "hello" in result.stdout
    assert not result.timed_out


@pytest.mark.asyncio
async def test_run_command_nonzero_exit(tmp_path: Path):
    import sys

    result = await process_runner.run_command(
        [sys.executable, "-c", "import sys; sys.exit(1)"], cwd=str(tmp_path), timeout_seconds=15
    )

    assert not result.passed
    assert result.exit_code == 1


@pytest.mark.asyncio
async def test_run_command_missing_binary(tmp_path: Path):
    result = await process_runner.run_command(
        ["this-binary-does-not-exist-anywhere"], cwd=str(tmp_path), timeout_seconds=15
    )

    assert not result.passed
    assert result.exit_code is None
    assert result.stderr


@pytest.mark.asyncio
async def test_run_command_timeout(tmp_path: Path):
    import sys

    result = await process_runner.run_command(
        [sys.executable, "-c", "import time; time.sleep(30)"], cwd=str(tmp_path), timeout_seconds=1
    )

    assert result.timed_out
    assert not result.passed


@pytest.mark.asyncio
async def test_run_command_wraps_cmd_launcher_on_windows(monkeypatch, tmp_path: Path):
    """npm/npx are .cmd files on Windows; CreateProcess can't exec them
    directly, so run_command must route them through cmd.exe /c."""
    monkeypatch.setattr(process_runner.os, "name", "nt")

    captured_args = {}

    class _FakeProc:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured_args["args"] = args
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    await process_runner.run_command(
        [r"C:\Program Files\nodejs\npm.cmd", "test"], cwd=str(tmp_path), timeout_seconds=15
    )

    assert captured_args["args"][:2] == ("cmd.exe", "/c")


@pytest.mark.asyncio
async def test_run_command_does_not_wrap_exe(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(process_runner.os, "name", "nt")

    captured_args = {}

    class _FakeProc:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured_args["args"] = args
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    await process_runner.run_command(
        [r"C:\Program Files\dotnet\dotnet.exe", "build"], cwd=str(tmp_path), timeout_seconds=15
    )

    assert captured_args["args"][0] == r"C:\Program Files\dotnet\dotnet.exe"


# ------------------------------------------------------------------
# diagnostics
# ------------------------------------------------------------------

def test_parse_dotnet_diagnostics_extracts_errors_and_warnings():
    output = (
        r"C:\Projects\App\ViewModels\MainViewModel.cs(146,17): error CS0103: "
        "The name 'ValidationMessage' does not exist in the current context [C:\\Projects\\App\\App.csproj]\n"
        r"C:\Projects\App\Program.cs(10,5): warning CS0168: "
        "The variable 'x' is declared but never used [C:\\Projects\\App\\App.csproj]\n"
        "Build FAILED.\n"
    )

    diags = diagnostics.parse_dotnet_diagnostics(output)

    assert len(diags) == 2
    assert diags[0] == {
        "file": r"C:\Projects\App\ViewModels\MainViewModel.cs",
        "line": 146,
        "column": 17,
        "severity": "error",
        "code": "CS0103",
        "message": "The name 'ValidationMessage' does not exist in the current context",
    }
    assert diags[1]["severity"] == "warning"
    assert diags[1]["code"] == "CS0168"


def test_parse_dotnet_diagnostics_ignores_unrelated_lines():
    output = "Restore complete.\nBuild succeeded.\n    0 Warning(s)\n    0 Error(s)\n"

    diags = diagnostics.parse_dotnet_diagnostics(output)

    assert diags == []


# ------------------------------------------------------------------
# diagnostics.fingerprint_stage (baseline tracking)
# ------------------------------------------------------------------

def test_fingerprint_stage_passed_is_empty():
    stage = {"passed": True, "name": "build", "diagnostics": []}

    assert diagnostics.fingerprint_stage(stage) == frozenset()


def test_fingerprint_stage_ignores_line_and_column():
    """Fingerprints must survive line shifts from an earlier edit in the
    same file - only (file, code, message) identify a diagnostic."""
    stage_before = {
        "passed": False, "name": "build",
        "diagnostics": [{"file": "A.cs", "line": 10, "column": 1, "severity": "error", "code": "CS1", "message": "boom"}],
    }
    stage_after_shift = {
        "passed": False, "name": "build",
        "diagnostics": [{"file": "A.cs", "line": 25, "column": 5, "severity": "error", "code": "CS1", "message": "boom"}],
    }

    assert diagnostics.fingerprint_stage(stage_before) == diagnostics.fingerprint_stage(stage_after_shift)


def test_fingerprint_stage_ignores_warnings():
    stage = {
        "passed": False, "name": "build",
        "diagnostics": [{"file": "A.cs", "line": 1, "column": 1, "severity": "warning", "code": "CS1", "message": "unused"}],
    }

    # No error-severity diagnostics -> falls back to the whole-stage sentinel.
    assert diagnostics.fingerprint_stage(stage) == frozenset({("__stage_failed__", "build", "")})


def test_fingerprint_stage_without_diagnostics_uses_stage_sentinel():
    stage = {"passed": False, "name": "test", "diagnostics": []}

    fp = diagnostics.fingerprint_stage(stage)

    assert fp == frozenset({("__stage_failed__", "test", "")})
    # Different stage name -> different sentinel, so it won't be confused
    # with a different stage's pre-existing failure.
    other = diagnostics.fingerprint_stage({"passed": False, "name": "build", "diagnostics": []})
    assert fp != other


# ------------------------------------------------------------------
# gate_controller (adapters monkeypatched - no real dotnet/npm required)
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_gate_for_root_uses_selected_adapter(monkeypatch, tmp_path: Path):
    async def fake_dotnet_gate(root, cfg):
        return {"passed": False, "skipped": False, "reason": "", "stages": [{"name": "build", "passed": False}]}

    monkeypatch.setitem(gate_controller._ADAPTERS, "dotnet", fake_dotnet_gate)

    result = await gate_controller.run_gate_for_root(str(tmp_path), "dotnet", {})

    assert result["passed"] is False
    assert result["kind"] == "dotnet"
    assert result["root"] == str(tmp_path)


@pytest.mark.asyncio
async def test_run_gate_for_root_unknown_kind_is_skipped(tmp_path: Path):
    result = await gate_controller.run_gate_for_root(str(tmp_path), "cobol", {})

    assert result["skipped"] is True
    assert result["passed"] is True


@pytest.mark.asyncio
async def test_run_gate_for_path_no_project_is_skipped(tmp_path: Path):
    result = await gate_controller.run_gate_for_path(str(tmp_path), {})

    assert result["skipped"] is True
    assert result["passed"] is True

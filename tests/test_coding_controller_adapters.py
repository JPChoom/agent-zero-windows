"""Tests for the Phase F language adapters (python, go, rust, java, cpp)
and project_detector.py's extended marker set. Toolchain presence is
monkeypatched for determinism rather than relying on what happens to be
installed in the CI/dev environment - matches this repo's existing
adapter test conventions (test_coding_controller.py's dotnet/npm
gate_controller tests do the same via _ADAPTERS monkeypatching).
"""

from pathlib import Path

import pytest

from plugins._coding_controller.helpers import config, project_detector
from plugins._coding_controller.helpers.adapters import cpp, go, java, python, rust
from plugins._coding_controller.helpers.process_runner import CommandResult


def _result(command, exit_code, stdout="", stderr=""):
    return CommandResult(command=command, exit_code=exit_code, timed_out=False, stdout=stdout, stderr=stderr, duration_ms=1)


# ------------------------------------------------------------------
# project_detector - new markers
# ------------------------------------------------------------------

def test_detect_python_via_pyproject_toml(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")

    info = project_detector.detect_project(str(tmp_path))

    assert info is not None
    assert info.kind == "python"
    assert info.marker == "pyproject.toml"


def test_detect_python_via_requirements_txt(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("", encoding="utf-8")

    info = project_detector.detect_project(str(tmp_path))

    assert info.kind == "python"


def test_detect_go_via_go_mod(tmp_path: Path):
    (tmp_path / "go.mod").write_text("module example.com/x\n", encoding="utf-8")

    info = project_detector.detect_project(str(tmp_path))

    assert info is not None
    assert info.kind == "go"
    assert info.marker == "go.mod"


def test_detect_rust_via_cargo_toml(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text("[package]\n", encoding="utf-8")

    info = project_detector.detect_project(str(tmp_path))

    assert info is not None
    assert info.kind == "rust"


def test_detect_java_via_pom_xml(tmp_path: Path):
    (tmp_path / "pom.xml").write_text("", encoding="utf-8")

    info = project_detector.detect_project(str(tmp_path))

    assert info is not None
    assert info.kind == "java"
    assert info.marker == "pom.xml"


def test_detect_java_via_build_gradle_kts(tmp_path: Path):
    (tmp_path / "build.gradle.kts").write_text("", encoding="utf-8")

    info = project_detector.detect_project(str(tmp_path))

    assert info.kind == "java"
    assert info.marker == "build.gradle.kts"


def test_detect_cpp_via_cmakelists(tmp_path: Path):
    (tmp_path / "CMakeLists.txt").write_text("", encoding="utf-8")

    info = project_detector.detect_project(str(tmp_path))

    assert info is not None
    assert info.kind == "cpp"


def test_dotnet_still_takes_priority_over_new_markers_at_same_level(tmp_path: Path):
    (tmp_path / "MyApp.csproj").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "go.mod").write_text("", encoding="utf-8")

    info = project_detector.detect_project(str(tmp_path))

    assert info.kind == "dotnet"


def test_java_takes_priority_over_python_at_same_level(tmp_path: Path):
    (tmp_path / "pom.xml").write_text("", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("", encoding="utf-8")

    info = project_detector.detect_project(str(tmp_path))

    assert info.kind == "java"


# ------------------------------------------------------------------
# python.py
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_python_skipped_when_neither_ruff_nor_pytest_found(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(python, "find_ruff", lambda: "")
    monkeypatch.setattr(python, "find_pytest", lambda: "")

    result = await python.run_gate(str(tmp_path), {})

    assert result["skipped"] is True
    assert result["passed"] is True


@pytest.mark.asyncio
async def test_python_runs_only_pytest_when_ruff_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(python, "find_ruff", lambda: "")
    monkeypatch.setattr(python, "find_pytest", lambda: "pytest")

    async def fake_run_command(args, cwd, timeout_seconds):
        return _result(args, 0)

    monkeypatch.setattr(python, "run_command", fake_run_command)

    result = await python.run_gate(str(tmp_path), {})

    assert result["skipped"] is False
    assert [s["name"] for s in result["stages"]] == ["pytest"]


@pytest.mark.asyncio
async def test_python_runs_ruff_and_pytest_when_both_found(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(python, "find_ruff", lambda: "ruff")
    monkeypatch.setattr(python, "find_pytest", lambda: "pytest")

    async def fake_run_command(args, cwd, timeout_seconds):
        return _result(args, 0)

    monkeypatch.setattr(python, "run_command", fake_run_command)

    result = await python.run_gate(str(tmp_path), {"python_test_args": "-x"})

    names = [s["name"] for s in result["stages"]]
    assert names == ["ruff-check", "ruff-format", "pytest"]
    pytest_stage = result["stages"][2]
    assert pytest_stage["command"] == "pytest -x"


@pytest.mark.asyncio
async def test_python_fails_when_a_stage_fails(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(python, "find_ruff", lambda: "ruff")
    monkeypatch.setattr(python, "find_pytest", lambda: "")

    async def fake_run_command(args, cwd, timeout_seconds):
        return _result(args, 1, stderr="lint error")

    monkeypatch.setattr(python, "run_command", fake_run_command)

    result = await python.run_gate(str(tmp_path), {})

    assert result["passed"] is False


# ------------------------------------------------------------------
# go.py
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_go_skipped_when_go_not_found(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(go, "find_go", lambda: "")

    result = await go.run_gate(str(tmp_path), {})

    assert result["skipped"] is True


@pytest.mark.asyncio
async def test_go_omits_gofmt_stage_when_gofmt_not_found(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(go, "find_go", lambda: "go")
    monkeypatch.setattr(go, "find_gofmt", lambda: "")

    async def fake_run_command(args, cwd, timeout_seconds):
        return _result(args, 0)

    monkeypatch.setattr(go, "run_command", fake_run_command)

    result = await go.run_gate(str(tmp_path), {})

    names = [s["name"] for s in result["stages"]]
    assert "gofmt" not in names
    assert names == ["go-vet", "go-build", "go-test"]


@pytest.mark.asyncio
async def test_go_gofmt_fails_when_files_need_formatting_despite_exit_zero(monkeypatch, tmp_path: Path):
    """gofmt -l always exits 0 - it just lists files needing formatting.
    A non-empty stdout must be treated as a failure."""
    monkeypatch.setattr(go, "find_go", lambda: "go")
    monkeypatch.setattr(go, "find_gofmt", lambda: "gofmt")

    async def fake_run_command(args, cwd, timeout_seconds):
        if args[0] == "gofmt":
            return _result(args, 0, stdout="main.go\n")
        return _result(args, 0)

    monkeypatch.setattr(go, "run_command", fake_run_command)

    result = await go.run_gate(str(tmp_path), {})

    gofmt_stage = next(s for s in result["stages"] if s["name"] == "gofmt")
    assert gofmt_stage["exit_code"] == 0
    assert gofmt_stage["passed"] is False
    assert result["passed"] is False


@pytest.mark.asyncio
async def test_go_gofmt_passes_when_no_files_listed(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(go, "find_go", lambda: "go")
    monkeypatch.setattr(go, "find_gofmt", lambda: "gofmt")

    async def fake_run_command(args, cwd, timeout_seconds):
        return _result(args, 0, stdout="")

    monkeypatch.setattr(go, "run_command", fake_run_command)

    result = await go.run_gate(str(tmp_path), {})

    gofmt_stage = next(s for s in result["stages"] if s["name"] == "gofmt")
    assert gofmt_stage["passed"] is True
    assert result["passed"] is True


@pytest.mark.asyncio
async def test_go_test_args_configurable(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(go, "find_go", lambda: "go")
    monkeypatch.setattr(go, "find_gofmt", lambda: "")
    captured = {}

    async def fake_run_command(args, cwd, timeout_seconds):
        if args[1] == "test":
            captured["args"] = args
        return _result(args, 0)

    monkeypatch.setattr(go, "run_command", fake_run_command)

    await go.run_gate(str(tmp_path), {"go_test_args": "./pkg/... -run TestFoo"})

    assert captured["args"] == ["go", "test", "./pkg/...", "-run", "TestFoo"]


# ------------------------------------------------------------------
# rust.py
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rust_skipped_when_cargo_not_found(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(rust, "find_cargo", lambda: "")

    result = await rust.run_gate(str(tmp_path), {})

    assert result["skipped"] is True


@pytest.mark.asyncio
async def test_rust_runs_all_four_stages_regardless_of_earlier_failures(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(rust, "find_cargo", lambda: "cargo")
    call_count = {"n": 0}

    async def fake_run_command(args, cwd, timeout_seconds):
        call_count["n"] += 1
        return _result(args, 1)  # every stage fails

    monkeypatch.setattr(rust, "run_command", fake_run_command)

    result = await rust.run_gate(str(tmp_path), {})

    assert call_count["n"] == 4
    assert [s["name"] for s in result["stages"]] == ["cargo-fmt", "cargo-clippy", "cargo-build", "cargo-test"]
    assert result["passed"] is False


@pytest.mark.asyncio
async def test_rust_build_args_configurable(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(rust, "find_cargo", lambda: "cargo")
    captured = {}

    async def fake_run_command(args, cwd, timeout_seconds):
        if "cargo-build" not in captured and "build" in args or "check" in args:
            captured["build_args"] = args
        return _result(args, 0)

    monkeypatch.setattr(rust, "run_command", fake_run_command)

    await rust.run_gate(str(tmp_path), {"rust_build_args": "check --all-targets"})

    assert captured["build_args"] == ["cargo", "check", "--all-targets"]


# ------------------------------------------------------------------
# java.py
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_java_skipped_when_no_marker_present(tmp_path: Path):
    result = await java.run_gate(str(tmp_path), {})

    assert result["skipped"] is True


@pytest.mark.asyncio
async def test_java_uses_maven_when_pom_present(monkeypatch, tmp_path: Path):
    (tmp_path / "pom.xml").write_text("", encoding="utf-8")
    monkeypatch.setattr(java, "find_maven", lambda: "mvn")

    async def fake_run_command(args, cwd, timeout_seconds):
        return _result(args, 0)

    monkeypatch.setattr(java, "run_command", fake_run_command)

    result = await java.run_gate(str(tmp_path), {})

    assert result["stages"][0]["name"] == "mvn-test"
    assert result["stages"][0]["command"] == "mvn test"


@pytest.mark.asyncio
async def test_java_prefers_mvnw_wrapper_over_global_mvn(monkeypatch, tmp_path: Path):
    (tmp_path / "pom.xml").write_text("", encoding="utf-8")
    (tmp_path / "mvnw").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(java, "find_maven", lambda: "C:\\global\\mvn.cmd")

    async def fake_run_command(args, cwd, timeout_seconds):
        return _result(args, 0)

    monkeypatch.setattr(java, "run_command", fake_run_command)

    result = await java.run_gate(str(tmp_path), {})

    assert "mvnw" in result["stages"][0]["command"]


@pytest.mark.asyncio
async def test_java_uses_gradle_when_build_gradle_present(monkeypatch, tmp_path: Path):
    (tmp_path / "build.gradle").write_text("", encoding="utf-8")
    monkeypatch.setattr(java, "find_gradle", lambda: "gradle")

    async def fake_run_command(args, cwd, timeout_seconds):
        return _result(args, 0)

    monkeypatch.setattr(java, "run_command", fake_run_command)

    result = await java.run_gate(str(tmp_path), {})

    assert result["stages"][0]["name"] == "gradle-test"


@pytest.mark.asyncio
async def test_java_pom_takes_priority_over_gradle_marker(monkeypatch, tmp_path: Path):
    (tmp_path / "pom.xml").write_text("", encoding="utf-8")
    (tmp_path / "build.gradle").write_text("", encoding="utf-8")
    monkeypatch.setattr(java, "find_maven", lambda: "mvn")

    async def fake_run_command(args, cwd, timeout_seconds):
        return _result(args, 0)

    monkeypatch.setattr(java, "run_command", fake_run_command)

    result = await java.run_gate(str(tmp_path), {})

    assert result["stages"][0]["name"] == "mvn-test"


@pytest.mark.asyncio
async def test_java_skipped_when_pom_present_but_no_maven_available(monkeypatch, tmp_path: Path):
    (tmp_path / "pom.xml").write_text("", encoding="utf-8")
    monkeypatch.setattr(java, "find_maven", lambda: "")

    result = await java.run_gate(str(tmp_path), {})

    assert result["skipped"] is True


# ------------------------------------------------------------------
# cpp.py
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cpp_skipped_when_cmake_not_found(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cpp, "find_cmake", lambda: "")

    result = await cpp.run_gate(str(tmp_path), {})

    assert result["skipped"] is True


@pytest.mark.asyncio
async def test_cpp_stops_after_failed_configure(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cpp, "find_cmake", lambda: "cmake")
    monkeypatch.setattr(cpp, "find_clang_format", lambda: "")
    monkeypatch.setattr(cpp, "find_ctest", lambda: "")
    call_count = {"n": 0}

    async def fake_run_command(args, cwd, timeout_seconds):
        call_count["n"] += 1
        return _result(args, 1, stderr="configure failed")

    monkeypatch.setattr(cpp, "run_command", fake_run_command)

    result = await cpp.run_gate(str(tmp_path), {})

    assert call_count["n"] == 1  # only configure ran, build/test never attempted
    assert [s["name"] for s in result["stages"]] == ["cmake-configure"]
    assert result["passed"] is False


@pytest.mark.asyncio
async def test_cpp_runs_build_and_ctest_when_configure_passes(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cpp, "find_cmake", lambda: "cmake")
    monkeypatch.setattr(cpp, "find_clang_format", lambda: "")
    monkeypatch.setattr(cpp, "find_clang_tidy", lambda: "")
    monkeypatch.setattr(cpp, "find_ctest", lambda: "ctest")

    async def fake_run_command(args, cwd, timeout_seconds):
        return _result(args, 0)

    monkeypatch.setattr(cpp, "run_command", fake_run_command)

    result = await cpp.run_gate(str(tmp_path), {})

    assert [s["name"] for s in result["stages"]] == ["cmake-configure", "cmake-build", "ctest"]
    assert result["passed"] is True


@pytest.mark.asyncio
async def test_cpp_skips_ctest_stage_when_ctest_not_found(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cpp, "find_cmake", lambda: "cmake")
    monkeypatch.setattr(cpp, "find_clang_format", lambda: "")
    monkeypatch.setattr(cpp, "find_clang_tidy", lambda: "")
    monkeypatch.setattr(cpp, "find_ctest", lambda: "")

    async def fake_run_command(args, cwd, timeout_seconds):
        return _result(args, 0)

    monkeypatch.setattr(cpp, "run_command", fake_run_command)

    result = await cpp.run_gate(str(tmp_path), {})

    assert [s["name"] for s in result["stages"]] == ["cmake-configure", "cmake-build"]


@pytest.mark.asyncio
async def test_cpp_runs_clang_format_on_source_files_when_found(monkeypatch, tmp_path: Path):
    (tmp_path / "main.cpp").write_text("int main(){return 0;}", encoding="utf-8")
    (tmp_path / "README.md").write_text("hi", encoding="utf-8")
    monkeypatch.setattr(cpp, "find_cmake", lambda: "cmake")
    monkeypatch.setattr(cpp, "find_clang_format", lambda: "clang-format")
    monkeypatch.setattr(cpp, "find_clang_tidy", lambda: "")
    monkeypatch.setattr(cpp, "find_ctest", lambda: "")

    async def fake_run_command(args, cwd, timeout_seconds):
        return _result(args, 0)

    monkeypatch.setattr(cpp, "run_command", fake_run_command)

    result = await cpp.run_gate(str(tmp_path), {})

    fmt_stage = next(s for s in result["stages"] if s["name"] == "clang-format")
    assert "main.cpp" in fmt_stage["command"]
    assert "README.md" not in fmt_stage["command"]


@pytest.mark.asyncio
async def test_cpp_omits_clang_format_stage_when_no_source_files(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cpp, "find_cmake", lambda: "cmake")
    monkeypatch.setattr(cpp, "find_clang_format", lambda: "clang-format")
    monkeypatch.setattr(cpp, "find_clang_tidy", lambda: "")
    monkeypatch.setattr(cpp, "find_ctest", lambda: "")

    async def fake_run_command(args, cwd, timeout_seconds):
        return _result(args, 0)

    monkeypatch.setattr(cpp, "run_command", fake_run_command)

    result = await cpp.run_gate(str(tmp_path), {})

    assert "clang-format" not in [s["name"] for s in result["stages"]]


# ------------------------------------------------------------------
# config.py - new per-language fields default and normalize correctly
# ------------------------------------------------------------------

def test_get_config_new_language_fields_have_expected_defaults(monkeypatch):
    import helpers.plugins as plugins_module

    monkeypatch.setattr(plugins_module, "get_plugin_config", lambda plugin_name, agent=None: {})

    cfg = config.get_config(None)

    assert cfg["python_test_args"] == ""
    assert cfg["go_test_args"] == "./..."
    assert cfg["rust_build_args"] == "build"
    assert cfg["java_maven_test_args"] == "test"
    assert cfg["java_gradle_test_args"] == "test"


def test_get_config_new_language_fields_read_stored_values(monkeypatch):
    import helpers.plugins as plugins_module

    monkeypatch.setattr(
        plugins_module,
        "get_plugin_config",
        lambda plugin_name, agent=None: {
            "python_test_args": "-x -k smoke",
            "go_test_args": "./... -run TestFoo",
            "rust_build_args": "check",
            "java_maven_test_args": "verify",
            "java_gradle_test_args": "check",
        },
    )

    cfg = config.get_config(None)

    assert cfg["python_test_args"] == "-x -k smoke"
    assert cfg["go_test_args"] == "./... -run TestFoo"
    assert cfg["rust_build_args"] == "check"
    assert cfg["java_maven_test_args"] == "verify"
    assert cfg["java_gradle_test_args"] == "check"

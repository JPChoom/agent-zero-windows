"""Tests for _text_editor's path containment (file_ops.confine_to_workdir):
workdir-only confinement, traversal/absolute-path rejection, and the
allowed_external_roots integration with _code_execution's config.

This containment was previously only verified through manual live-UI
testing (see git history) - this file closes that gap with an automated
regression test, and specifically covers the bug live testing found: the
agent could `dotnet build` an external project via _code_execution's "cwd"
arg, but text_editor had no way to read/patch that project's files at all,
since it only ever knew about the workdir root.
"""

from pathlib import Path
from unittest import mock

import pytest

from plugins._text_editor.helpers import file_ops
from helpers import plugins


@pytest.fixture(autouse=True)
def _use_tmp_path_as_workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_ops, "get_workdir_root", lambda: tmp_path)


@pytest.fixture(autouse=True)
def _no_external_roots_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Most tests shouldn't need _code_execution's config at all; default
    it to empty so a missing/misconfigured plugin config doesn't leak
    into unrelated test outcomes. Tests that need external roots override
    this explicitly with their own mock.patch."""
    monkeypatch.setattr(plugins, "get_plugin_config", lambda *a, **k: {"allowed_external_roots": ""})


def test_relative_path_resolves_inside_workdir(tmp_path: Path):
    resolved = file_ops.confine_to_workdir("sub/file.txt")

    assert resolved == str(tmp_path / "sub" / "file.txt")


def test_absolute_path_inside_workdir_is_allowed(tmp_path: Path):
    target = tmp_path / "file.txt"

    resolved = file_ops.confine_to_workdir(str(target))

    assert resolved == str(target)


def test_absolute_path_outside_workdir_is_rejected():
    with pytest.raises(file_ops.PathNotAllowedError):
        file_ops.confine_to_workdir(r"C:\Windows\System32\config.sys")


def test_traversal_escape_is_rejected(tmp_path: Path):
    with pytest.raises(file_ops.PathNotAllowedError):
        file_ops.confine_to_workdir("../../Windows/System32")


def test_read_file_rejects_path_outside_workdir(tmp_path: Path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    result = file_ops.read_file(str(outside))

    assert result["error"]
    assert "outside the allowed working director" in result["error"]


# ------------------------------------------------------------------
# allowed_external_roots integration (_code_execution's config)
# ------------------------------------------------------------------

def test_external_root_configured_allows_access(tmp_path_factory, monkeypatch: pytest.MonkeyPatch):
    external = tmp_path_factory.mktemp("SafetyTestApp")
    target = external / "Program.cs"
    target.write_text("using System;\n", encoding="utf-8")

    monkeypatch.setattr(
        plugins, "get_plugin_config", lambda *a, **k: {"allowed_external_roots": str(external)}
    )

    result = file_ops.read_file(str(target))

    assert not result["error"]
    assert "using System" in result["content"]


def test_external_root_not_configured_still_rejected(tmp_path_factory, monkeypatch: pytest.MonkeyPatch):
    external = tmp_path_factory.mktemp("SafetyTestApp")
    target = external / "Program.cs"
    target.write_text("using System;\n", encoding="utf-8")

    monkeypatch.setattr(plugins, "get_plugin_config", lambda *a, **k: {"allowed_external_roots": ""})

    result = file_ops.read_file(str(target))

    assert result["error"]
    assert "outside the allowed working director" in result["error"]


def test_write_file_succeeds_inside_configured_external_root(tmp_path_factory, monkeypatch: pytest.MonkeyPatch):
    external = tmp_path_factory.mktemp("SafetyTestApp")
    target = external / "Program.cs"
    target.write_text("using System;\n", encoding="utf-8")

    monkeypatch.setattr(
        plugins, "get_plugin_config", lambda *a, **k: {"allowed_external_roots": str(external)}
    )

    result = file_ops.write_file(str(target), "using System;\nConsole.WriteLine(1);\n")

    assert not result["error"]
    assert target.read_text(encoding="utf-8") == "using System;\nConsole.WriteLine(1);\n"


def test_multiple_external_roots_one_line_each(tmp_path_factory, monkeypatch: pytest.MonkeyPatch):
    root_a = tmp_path_factory.mktemp("AppA")
    root_b = tmp_path_factory.mktemp("AppB")
    (root_a / "x.txt").write_text("a", encoding="utf-8")
    (root_b / "y.txt").write_text("b", encoding="utf-8")

    monkeypatch.setattr(
        plugins,
        "get_plugin_config",
        lambda *a, **k: {"allowed_external_roots": f"{root_a}\n{root_b}"},
    )

    result_a = file_ops.read_file(str(root_a / "x.txt"))
    result_b = file_ops.read_file(str(root_b / "y.txt"))

    assert not result_a["error"]
    assert not result_b["error"]


def test_get_plugin_config_failure_falls_back_to_workdir_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """If reading _code_execution's config fails for any reason, text_editor
    must still work for the workdir - it should not itself start raising."""

    def _raise(*a, **k):
        raise RuntimeError("plugin config unavailable")

    monkeypatch.setattr(plugins, "get_plugin_config", _raise)

    resolved = file_ops.confine_to_workdir("file.txt")

    assert resolved == str(tmp_path / "file.txt")

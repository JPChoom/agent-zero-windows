"""The file editor never writes to a Startup folder (enforcement audit E9).

The command safety floor denies shell commands that write there; with
access_tier "unrestricted" the editor was a way around it.
"""

from __future__ import annotations

import pytest

from plugins._text_editor.helpers import file_ops


@pytest.fixture
def unrestricted(monkeypatch, tmp_path):
    monkeypatch.setattr(file_ops, "_get_access_config", lambda: ("unrestricted", []))
    monkeypatch.setattr(file_ops, "get_workdir_root", lambda: tmp_path / "workdir")
    (tmp_path / "workdir").mkdir()
    return tmp_path


def _startup(root):
    folder = root / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    folder.mkdir(parents=True)
    return folder


def test_write_to_startup_folder_is_refused(unrestricted):
    target = _startup(unrestricted) / "run.bat"
    result = file_ops.write_file(str(target), "calc.exe")
    assert "Startup folder" in result["error"]
    assert not target.exists()


def test_all_users_startup_is_refused_too(unrestricted):
    folder = unrestricted / "ProgramData" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "StartUp"
    folder.mkdir(parents=True)
    result = file_ops.write_file(str(folder / "x.cmd"), "calc.exe")
    assert result["error"] and not (folder / "x.cmd").exists()


def test_patching_a_file_in_startup_is_refused(unrestricted):
    target = _startup(unrestricted) / "existing.bat"
    target.write_text("echo hi\n", encoding="utf-8")
    with pytest.raises(file_ops.PathNotAllowedError):
        file_ops.apply_exact_replace_file(str(target), "echo hi", "calc.exe")
    assert target.read_text(encoding="utf-8") == "echo hi\n"


def test_reading_and_ordinary_writes_still_work(unrestricted):
    target = _startup(unrestricted) / "notes.txt"
    target.write_text("hello\n", encoding="utf-8")
    assert file_ops.read_file(str(target))["error"] == ""
    elsewhere = unrestricted / "Documents" / "ok.txt"
    elsewhere.parent.mkdir()
    assert file_ops.write_file(str(elsewhere), "fine")["error"] == ""
    assert elsewhere.read_text(encoding="utf-8") == "fine"

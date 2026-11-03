"""Upstream's "/a0/..." container paths on a native Windows install.

A terminal resolves "/a0/x" on the current drive, so for any install not at
C:\\a0 (the README clones into another folder) the agent's terminal started
in C:\\a0\\usr\\workdir and commands with "/a0/..." paths hit that folder.
Found 2026-11-02: a0-dev's benchmark agent wrote into the live install's
workdir. Stored and compared paths keep the portable "/a0/" form; the agent,
the terminal and its working folder get real paths.
"""

from __future__ import annotations

import dataclasses
import os
import sys

import pytest

from helpers import files, runtime

pytestmark = pytest.mark.skipif(os.name != "nt", reason="native Windows behavior")


@pytest.fixture
def install(tmp_path, monkeypatch):
    base = tmp_path / "agent-zero-windows"
    (base / "usr" / "workdir").mkdir(parents=True)
    monkeypatch.setattr(files, "_base_dir", str(base))
    monkeypatch.setattr(runtime, "is_dockerized", lambda: False)
    return base


def _fwd(path) -> str:
    return os.path.normpath(str(path)).replace(chr(92), "/")


def test_a0_paths_become_this_installs_real_folder(install):
    assert files.native_path("/a0/usr/workdir") == os.path.normpath(install / "usr" / "workdir")
    assert files.native_path("/a0") == os.path.normpath(install)
    assert files.native_path("C:/elsewhere/x") == "C:/elsewhere/x"  # other paths untouched
    assert files.get_abs_path_dockerized("usr/workdir") == os.path.normpath(install / "usr" / "workdir")
    # what the agent is shown vs. what is stored and compared
    project = str(install / "usr" / "projects" / "demo")
    assert files.normalize_a0_path(project) == "/a0/usr/projects/demo"
    assert files.agent_path(project) == os.path.normpath(project)


def test_the_container_keeps_the_a0_form(install, monkeypatch):
    monkeypatch.setattr(runtime, "is_dockerized", lambda: True)
    assert files.native_path("/a0/usr/workdir") == "/a0/usr/workdir"
    assert files.rewrite_a0_paths("ls /a0/usr") == "ls /a0/usr"


@pytest.mark.parametrize("command,expected", [
    ("Get-ChildItem /a0/usr/workdir", "Get-ChildItem {b}/usr/workdir"),
    ('python /a0/skills/x/run.py --out "/a0/usr/out.txt"', 'python {b}/skills/x/run.py --out "{b}/usr/out.txt"'),
    ("cd /a0", "cd {b}"),
    ("Test-Path /a0/usr/x;echo hi", "Test-Path {b}/usr/x;echo hi"),
    ("open('/a0/usr/w.txt')", "open('{b}/usr/w.txt')"),
    # not a path of this install: left alone
    ("curl https://example.com/a0/usr", "curl https://example.com/a0/usr"),
    ("git log -- src/a0/file", "git log -- src/a0/file"),
    ("echo C:/a0/usr", "echo C:/a0/usr"),
    ("dir /a0b/x", "dir /a0b/x"),
    ("dir x/a0/y", "dir x/a0/y"),
])
def test_terminal_commands_with_a0_paths_run_against_this_install(install, command, expected):
    assert files.rewrite_a0_paths(command) == expected.format(b=_fwd(install))


def test_a_stored_a0_workdir_setting_is_read_as_the_real_folder(monkeypatch):
    from helpers import settings

    monkeypatch.setattr(runtime, "is_dockerized", lambda: False)
    real = os.path.normpath(files.get_abs_path("usr", "workdir"))  # this checkout's own config files
    normalized = settings.normalize_settings({**settings.get_default_settings(), "workdir_path": "/a0/usr/workdir"})
    assert normalized["workdir_path"] == real
    assert settings.get_default_settings()["workdir_path"] == real


def test_the_terminal_never_starts_in_an_a0_folder(install):
    from plugins._code_execution.helpers.shell_local import LocalInteractiveSession

    assert LocalInteractiveSession(cwd="/a0/usr/workdir").cwd == os.path.normpath(install / "usr" / "workdir")
    assert LocalInteractiveSession(cwd=None).cwd is None


def test_the_agent_sees_attachments_at_their_real_path_and_the_ui_keeps_a0(install):
    from agent import UserMessage
    import importlib

    ext = importlib.import_module(
        "extensions.python._functions.agent.Agent.hist_add_user_message.start._10_native_attachment_paths")
    message = UserMessage(message="see file", attachments=["/a0/usr/uploads/a.csv", "C:/x/b.txt"])
    data = {"args": (object(), message), "kwargs": {}}
    ext.NativeAttachmentPaths(agent=None).execute(data=data)
    shown = data["args"][1]
    assert shown.attachments == [os.path.normpath(install / "usr" / "uploads" / "a.csv"), "C:/x/b.txt"]
    assert message.attachments == ["/a0/usr/uploads/a.csv", "C:/x/b.txt"]  # stored message unchanged

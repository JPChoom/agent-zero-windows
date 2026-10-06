"""Start at logon: the per-user Startup entry (against a fake registry, never
the real one) and the no-window launcher (a real child process, from a
temporary folder)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import socket
import sys
import time
from pathlib import Path

import pytest

from plugins._autostart.helpers import startup

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows Startup entry")


class FakeRegistry:
    def __init__(self):
        self.values = {}

    def get(self, key, name):
        return self.values.get((key, name))

    def set_str(self, key, name, value):
        self.values[(key, name)] = value

    def delete(self, key, name):
        self.values.pop((key, name), None)


def test_enable_writes_one_quoted_run_value_and_disable_removes_it():
    reg = FakeRegistry()
    assert startup.status(reg)["enabled"] is False

    state = startup.enable(reg)
    cmd = reg.get(startup.RUN_KEY, startup.VALUE_NAME)
    assert cmd == startup.command() and cmd.startswith('"') and "pythonw.exe" in cmd and "launch_agent_zero.pyw" in cmd
    assert state["enabled"] and state["points_here"]

    state = startup.disable(reg)
    assert reg.values == {} and not state["registered"]


def test_task_manager_switch_is_reported_and_enable_clears_it():
    reg = FakeRegistry()
    startup.enable(reg)
    reg.set_str(startup.APPROVED_KEY, startup.VALUE_NAME, b"\x03" + b"\x00" * 11)
    state = startup.status(reg)
    assert state["registered"] and state["disabled_in_task_manager"] and not state["enabled"]
    assert startup.enable(reg)["enabled"]
    assert reg.get(startup.APPROVED_KEY, startup.VALUE_NAME) is None


def test_an_entry_from_another_install_is_flagged():
    reg = FakeRegistry()
    reg.set_str(startup.RUN_KEY, startup.VALUE_NAME, r'"C:\other\pythonw.exe" "C:\other\launch.pyw"')
    state = startup.status(reg)
    assert state["registered"] and not state["points_here"]


# -- launcher ------------------------------------------------------------------

def _load_launcher():
    path = Path(startup.LAUNCHER)
    loader = importlib.machinery.SourceFileLoader("launch_agent_zero_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_launcher_reads_the_port_from_usr_env(tmp_path, monkeypatch):
    mod = _load_launcher()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    assert mod.web_ui_port() == 5000
    (tmp_path / "usr").mkdir()
    (tmp_path / "usr" / ".env").write_text('A=1\nWEB_UI_PORT="5123"\n', encoding="utf-8")
    assert mod.web_ui_port() == 5123


def test_launcher_does_nothing_when_agent_zero_already_answers(tmp_path, monkeypatch):
    mod = _load_launcher()
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen()
        port = srv.getsockname()[1]
        assert mod.already_running(port)
        monkeypatch.setattr(mod, "ROOT", tmp_path)
        monkeypatch.setattr(mod, "LOG", tmp_path / "logs" / "autostart.log")
        monkeypatch.setattr(mod, "web_ui_port", lambda: port)
        (tmp_path / "run_ui.py").write_text("open('started.txt','w').write('x')\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)  # main() chdirs to ROOT; restore cwd afterwards
        mod.main()
    time.sleep(1)
    assert not (tmp_path / "started.txt").exists()
    assert "already answers" in (tmp_path / "logs" / "autostart.log").read_text(encoding="utf-8")


def test_launcher_starts_the_server_hidden_and_logs_its_output(tmp_path, monkeypatch):
    mod = _load_launcher()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "LOG", tmp_path / "logs" / "autostart.log")
    monkeypatch.setattr(mod, "web_ui_port", _free_port)
    monkeypatch.setattr(mod, "python_exe", lambda: sys.executable)
    (tmp_path / "run_ui.py").write_text(
        "import os\nprint('stand-in server', os.getcwd())\nopen('started.txt','w').write('x')\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)  # main() chdirs to ROOT; restore cwd afterwards
    mod.main()
    for _ in range(50):
        if (tmp_path / "started.txt").exists():
            break
        time.sleep(0.2)
    assert (tmp_path / "started.txt").exists()
    time.sleep(0.5)
    log = (tmp_path / "logs" / "autostart.log").read_text(encoding="utf-8")
    assert "starting Agent Zero" in log and "stand-in server" in log

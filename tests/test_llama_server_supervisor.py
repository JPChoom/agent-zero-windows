"""The managed llama.cpp server supervisor (helpers/llama_server.py), driven
against a Python stand-in (tests/fixtures/fake_llama_server.py): no download,
no GPU. Real processes, real HTTP, real process-identity checks."""

from __future__ import annotations

import socket
import sys
import time
from pathlib import Path

import pytest

from helpers import llama_server as sup

FAKE = str(Path(__file__).resolve().parent / "fixtures" / "fake_llama_server.py")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(sup, "state_path", lambda: str(tmp_path / "server.json"))
    monkeypatch.setattr(sup, "log_path", lambda: str(tmp_path / "logs" / "llama-server.log"))
    monkeypatch.setattr(sup, "PROCESS_NAME_HINT", "python")
    monkeypatch.setattr(sup, "free_vram_mib", lambda: None)
    monkeypatch.setattr(sup, "RESTART_BACKOFF", (0.2, 0.2, 0.2))
    monkeypatch.setattr(sup, "MONITOR_INTERVAL", 0.2)
    monkeypatch.setattr(sup, "_notify", lambda message: None)
    model = tmp_path / "Qwen3-8B-Q4_K_M.gguf"
    model.write_bytes(b"GGUF" + b"\0" * 1024)
    made = []

    def config(**overrides):
        values = dict(binary=sys.executable, model=str(model), port=free_port(),
                      launcher_prefix=[FAKE], startup_timeout=20)
        values.update(overrides)
        return sup.ServerConfig(**values)

    def new_supervisor():
        s = sup.Supervisor()
        made.append(s)
        return s

    yield config, new_supervisor, tmp_path
    for s in made:
        s.stop()


def test_starts_and_verifies_the_loaded_model(env):
    config, new, _ = env
    s, cfg = new(), config()
    status = s.start(cfg)
    assert status["state"] == "running" and status["alias"] == "Qwen3-8B-Q4_K_M"
    assert status["api_base"] == f"http://127.0.0.1:{cfg.port}/v1"
    assert sup.is_ready(cfg.port)


def test_refuses_a_server_reporting_another_model(env, monkeypatch):
    config, new, _ = env
    monkeypatch.setenv("FAKE_WRONG_MODEL", "1")
    s, cfg = new(), config()
    with pytest.raises(sup.SupervisorError, match="not Qwen3"):
        s.start(cfg)
    assert s.status()["state"] == "failed"
    time.sleep(0.5)
    assert not sup.port_in_use(cfg.port)  # the wrong server was stopped


def test_refuses_a_port_used_by_another_program(env):
    config, new, _ = env
    cfg = config()
    with socket.socket() as other:
        other.bind(("127.0.0.1", cfg.port))
        other.listen(1)
        with pytest.raises(sup.SupervisorError, match="already used"):
            new().start(cfg)


def test_missing_files_and_vram_are_checked_before_launch(env, monkeypatch, tmp_path):
    config, new, _ = env
    with pytest.raises(sup.SupervisorError, match="not found"):
        new().start(config(binary=str(tmp_path / "nope.exe")))
    monkeypatch.setattr(sup, "free_vram_mib", lambda: 0)
    with pytest.raises(sup.SupervisorError, match="GPU memory"):
        new().start(config())
    # CPU only (0 GPU layers) needs no VRAM.
    assert new().start(config(gpu_layers=0))["state"] == "running"


def test_restarts_after_a_crash(env, monkeypatch):
    config, new, _ = env
    monkeypatch.setenv("FAKE_EXIT_AFTER", "1.0")
    s, cfg = new(), config()
    s.start(cfg)
    first_pid = s.status()["pid"]
    monkeypatch.delenv("FAKE_EXIT_AFTER")  # the restarted one stays up
    deadline = time.time() + 15
    while time.time() < deadline and (s.status()["pid"] == first_pid or s.status()["state"] != "running"):
        time.sleep(0.2)
    status = s.status()
    assert status["state"] == "running" and status["pid"] != first_pid and status["restarts"] == 1


def test_gives_up_after_repeated_crashes(env, monkeypatch):
    config, new, _ = env
    monkeypatch.setenv("FAKE_EXIT_AFTER", "0.6")
    monkeypatch.setattr(sup, "MAX_RESTARTS", 2)
    s = new()
    s.start(config())
    deadline = time.time() + 20
    while time.time() < deadline and s.status()["state"] != "failed":
        time.sleep(0.2)
    assert s.status()["state"] == "failed" and "not restarting" in s.status()["last_error"]


def test_stop_leaves_no_process_and_no_state(env):
    config, new, tmp = env
    s, cfg = new(), config()
    s.start(cfg)
    s.stop()
    time.sleep(0.3)
    assert not sup.port_in_use(cfg.port)
    assert not (tmp / "server.json").exists()


def test_a_leftover_identical_server_is_adopted(env):
    config, new, _ = env
    cfg = config()
    first = new()
    first.start(cfg)
    pid = first.status()["pid"]
    first._monitor = None  # simulate A0W being killed: the process keeps running
    first._proc = None
    second = new()
    status = second.start(cfg)
    assert status["adopted"] is True and status["pid"] == pid


def test_a_leftover_server_with_other_settings_is_replaced(env):
    config, new, _ = env
    cfg = config()
    first = new()
    first.start(cfg)
    old_pid = first.status()["pid"]
    first._proc = None
    changed = sup.ServerConfig(**{**cfg.__dict__, "context_size": 4096})
    status = new().start(changed)
    assert status["adopted"] is False and status["pid"] != old_pid
    import psutil

    assert not psutil.pid_exists(old_pid) or psutil.Process(old_pid).status() == psutil.STATUS_ZOMBIE


@pytest.mark.parametrize("bad", ["--host 0.0.0.0", "--port=9999", "--path C:\\", "-m other.gguf"])
def test_extra_args_cannot_override_what_the_supervisor_owns(bad):
    with pytest.raises(sup.SupervisorError):
        sup.parse_extra_args(bad)


def test_ordinary_extra_args_pass():
    assert sup.parse_extra_args("--flash-attn --temp 0.7") == ["--flash-attn", "--temp", "0.7"]

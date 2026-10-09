"""A restart hands the running Cloudflare tunnel to the new server process
(helpers/tunnel_manager.py write_handover / adopt_handover), so the remote
address keeps working. Adoption must only ever pick up the same cloudflared
process, forwarding to this server's port."""

import json
from types import SimpleNamespace

import psutil
import pytest

from helpers import process
from helpers import tunnel_manager as tm

PORT = 5000
URL = "https://example-tunnel.trycloudflare.com"


class _Proc:
    def __init__(self, pid=4242, create_time=1000.0, name="cloudflared.exe", port=PORT):
        self.pid = pid
        self._create_time = create_time
        self._name = name
        self._cmdline = ["cloudflared.exe", "tunnel", "--protocol", "quic", "--url", f"http://localhost:{port}"]
        self.terminated = False

    def create_time(self):
        return self._create_time

    def name(self):
        return self._name

    def cmdline(self):
        return self._cmdline

    def terminate(self):
        self.terminated = True


class _Popen:
    def __init__(self, pid=4242, exited=False):
        self.pid = pid
        self._exited = exited

    def poll(self):
        return 0 if self._exited else None


@pytest.fixture
def env(tmp_path, monkeypatch):
    handover = tmp_path / "handover.json"
    monkeypatch.setattr(tm, "files", SimpleNamespace(get_abs_path=lambda *_: str(handover)))
    procs = {}

    def fake_process(pid):
        if pid not in procs:
            raise psutil.NoSuchProcess(pid)
        return procs[pid]

    monkeypatch.setattr(psutil, "Process", fake_process)
    return SimpleNamespace(file=handover, procs=procs)


def _running_manager(provider="cloudflared", popen=None):
    m = tm.TunnelManager()
    m.provider = provider
    m.tunnel_url = URL
    m.is_running = True
    m.tunnel = SimpleNamespace(tunnel=SimpleNamespace(tunnel_process=popen or _Popen()))
    return m


def test_write_then_adopt_keeps_the_same_address(env):
    env.procs[4242] = _Proc()
    assert _running_manager().write_handover(PORT) is True
    assert json.loads(env.file.read_text())["url"] == URL

    fresh = tm.TunnelManager()
    assert fresh.adopt_handover(PORT) == URL
    assert fresh.is_running and fresh.provider == "cloudflared" and fresh.get_tunnel_url() == URL
    assert not env.file.exists()


@pytest.mark.parametrize("proc_change", [
    {"create_time": 2000.0},          # pid reused by another process
    {"name": "python.exe"},           # not cloudflared
    {"port": 5077},                   # forwards somewhere else
])
def test_adoption_refuses_anything_but_the_same_tunnel(env, proc_change):
    env.procs[4242] = _Proc()
    _running_manager().write_handover(PORT)
    env.procs[4242] = _Proc(**proc_change)
    fresh = tm.TunnelManager()
    assert fresh.adopt_handover(PORT) is None
    assert not fresh.is_running and not env.file.exists()


def test_adoption_refuses_a_dead_process_or_other_port(env):
    env.procs[4242] = _Proc()
    _running_manager().write_handover(PORT)
    assert tm.TunnelManager().adopt_handover(5077) is None  # restarted on another port

    _running_manager().write_handover(PORT)
    env.procs.clear()
    assert tm.TunnelManager().adopt_handover(PORT) is None


def test_nothing_is_written_without_a_live_cloudflared_tunnel(env):
    env.procs[4242] = _Proc()
    assert tm.TunnelManager().write_handover(PORT) is False
    assert _running_manager(provider="serveo").write_handover(PORT) is False
    assert _running_manager(popen=_Popen(exited=True)).write_handover(PORT) is False
    assert not env.file.exists()
    assert tm.TunnelManager().adopt_handover(PORT) is None


def test_an_adopted_tunnel_can_be_handed_over_again_and_stopped(env):
    env.procs[4242] = _Proc()
    _running_manager().write_handover(PORT)
    adopted = tm.TunnelManager()
    adopted.adopt_handover(PORT)

    assert adopted.write_handover(PORT) is True  # a second restart
    again = tm.TunnelManager()
    assert again.adopt_handover(PORT) == URL

    assert again.stop_tunnel() is True
    assert env.procs[4242].terminated and again.get_tunnel_url() is None


def test_stop_never_kills_a_reused_pid(env):
    env.procs[4242] = _Proc(create_time=2000.0)
    tm.AdoptedTunnel(4242, 1000.0, URL).stop()
    assert env.procs[4242].terminated is False


def test_reload_writes_the_handover_before_restarting(monkeypatch):
    calls = []
    manager = SimpleNamespace(write_handover=lambda port: calls.append(("handover", port)) or True)
    monkeypatch.setattr(tm.TunnelManager, "get_instance", classmethod(lambda cls: manager))
    monkeypatch.setattr(process.runtime, "is_dockerized", lambda: False)
    monkeypatch.setattr(process.runtime, "get_web_ui_port", lambda: PORT)
    monkeypatch.setattr(process, "restart_process", lambda: calls.append(("restart",)))
    process.reload()
    assert calls == [("handover", PORT), ("restart",)]

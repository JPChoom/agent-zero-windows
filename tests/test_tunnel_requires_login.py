"""Remote Control cannot be started without a login (investigation finding F2)."""

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api import tunnel, tunnel_proxy
from helpers import access_control


class ExplodingManager:
    def start_tunnel(self, *args, **kwargs):
        raise AssertionError("tunnel must not start without a login")


def test_tunnel_create_is_refused_without_login(monkeypatch):
    monkeypatch.setattr(access_control, "login_configured", lambda: False)
    monkeypatch.setattr(tunnel.TunnelManager, "get_instance", classmethod(lambda cls: ExplodingManager()))

    result = asyncio.run(tunnel.process({"action": "create", "provider": "cloudflared"}))

    assert result["success"] is False
    assert "Set a login first" in result["message"]


def test_tunnel_proxy_refuses_before_forwarding(monkeypatch):
    monkeypatch.setattr(access_control, "login_configured", lambda: False)

    def no_network(*args, **kwargs):
        raise AssertionError("must not contact the tunnel service")

    monkeypatch.setattr(tunnel_proxy.requests, "post", no_network)

    result = asyncio.run(tunnel_proxy.process({"action": "create", "provider": "cloudflared"}))

    assert result["success"] is False
    assert "Set a login first" in result["message"]


def test_other_tunnel_actions_still_work_without_login(monkeypatch):
    monkeypatch.setattr(access_control, "login_configured", lambda: False)

    assert asyncio.run(tunnel.process({"action": "health"})) == {"success": True}

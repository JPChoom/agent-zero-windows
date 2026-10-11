"""Investigation findings F8 (Secure session cookie over the tunnel) and F9
(the WebSocket test harness is opt-in)."""

from __future__ import annotations

import asyncio
import types

import pytest

from helpers import runtime, ui_server


@pytest.mark.parametrize("remote,headers,expected", [
    ("127.0.0.1", {"CF-Connecting-IP": "203.0.113.9", "CF-Visitor": '{"scheme":"https"}'}, True),
    ("127.0.0.1", {"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Proto": "https"}, True),
    ("127.0.0.1", {}, False),  # this PC over http://localhost
    ("127.0.0.1", {"X-Forwarded-Proto": "http", "X-Forwarded-For": "203.0.113.9"}, False),
    ("203.0.113.9", {"X-Forwarded-Proto": "https", "X-Forwarded-For": "1.2.3.4"}, False),  # not via a local tunnel
])
def test_https_is_recognised_only_through_a_local_tunnel(remote, headers, expected):
    assert ui_server.came_over_https(remote, headers) is expected


def test_session_cookie_is_secure_only_over_the_tunnel():
    from flask import Flask

    app = Flask(__name__)
    app.secret_key = "x"
    iface = ui_server._TunnelAwareSessionInterface()
    with app.test_request_context("/", headers={"CF-Connecting-IP": "203.0.113.9", "CF-Visitor": '{"scheme":"https"}'},
                                  environ_base={"REMOTE_ADDR": "127.0.0.1"}):
        assert iface.get_cookie_secure(app) is True
    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "127.0.0.1"}):
        assert iface.get_cookie_secure(app) is False


def test_dev_harness_is_off_unless_opted_in(monkeypatch):
    from api import ws_dev_test
    from helpers import dotenv

    monkeypatch.setattr(dotenv, "get_dotenv_value", lambda key, default=None: default)
    assert runtime.dev_harness_enabled() is False
    handler = object.__new__(ws_dev_test.WsDevTest)
    for event in ("ws_event_console_subscribe", "ws_tester_emit", "ws_tester_request_delayed"):
        result = asyncio.run(handler.process(event, {"delay_ms": 999999}, "sid"))
        assert result is not None and result._error and result._error.get("code") == "NOT_AVAILABLE"
    # Events for other handlers are not answered with an error.
    assert asyncio.run(handler.process("state_request", {}, "sid")) is None


def test_dev_harness_opt_in(monkeypatch):
    from helpers import dotenv

    monkeypatch.setattr(dotenv, "get_dotenv_value", lambda key, default=None: "1" if key == "A0_DEV_HARNESS" else default)
    assert runtime.dev_harness_enabled() is True

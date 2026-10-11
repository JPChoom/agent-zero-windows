"""WebSocket connect refuses sockets that are not signed in (investigation finding F1).

Before, the namespace accepted any same-origin socket, registered it with the
manager (which sends the runtime id and broadcasts a lifecycle event with the
new sid and connection count to every socket), and only then skipped the
handlers that required auth.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path

import pytest
from flask import Flask
from werkzeug.test import EnvironBuilder

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import helpers.ws as ws
from helpers import login


class FakeSocketServer:
    def __init__(self):
        self.handlers = {}

    def on(self, event, namespace=None):
        def register(fn):
            self.handlers[event] = fn
            return fn
        return register


class FakeManager:
    def __init__(self):
        self.connected = []

    async def handle_connect(self, namespace, sid, user_id=None):
        self.connected.append(sid)

    async def handle_disconnect(self, namespace, sid):
        pass


@pytest.fixture
def connect(monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test-secret"
    server = FakeSocketServer()
    manager = FakeManager()
    ws.register_ws_namespace(server, app, threading.Lock(), manager=manager)
    monkeypatch.setattr(ws, "validate_ws_origin", lambda environ: (True, None))
    session_data: dict = {}

    class FakeSession(dict):
        pass

    monkeypatch.setattr(ws, "session", FakeSession(session_data))

    def run(sid: str, authentication: str | None):
        ws.session.clear()
        if authentication is not None:
            ws.session["authentication"] = authentication
        environ = EnvironBuilder(
            path="/socket.io/", headers={"Origin": "http://localhost:5000"}
        ).get_environ()
        environ["REMOTE_ADDR"] = "127.0.0.1"
        result = asyncio.run(server.handlers["connect"](sid, environ, {"handlers": []}))
        return result, list(manager.connected)

    yield run
    with ws._contexts_lock:
        ws._ws_contexts.clear()
        ws._active_handlers.clear()


def test_unauthenticated_socket_is_refused_before_registration(connect, monkeypatch):
    monkeypatch.setattr(login, "get_credentials_hash", lambda: "the-hash")

    result, registered = connect("sid-anon", None)

    assert result is False
    assert registered == []  # no runtime id, no lifecycle broadcast
    assert "sid-anon" not in ws._ws_contexts


def test_wrong_session_hash_is_refused(connect, monkeypatch):
    monkeypatch.setattr(login, "get_credentials_hash", lambda: "the-hash")

    result, registered = connect("sid-stale", "an-old-hash")

    assert result is False
    assert registered == []


def test_signed_in_socket_connects(connect, monkeypatch):
    monkeypatch.setattr(login, "get_credentials_hash", lambda: "the-hash")

    result, registered = connect("sid-ok", "the-hash")

    assert result is True
    assert registered == ["sid-ok"]


def test_no_login_configured_still_connects(connect, monkeypatch):
    # Remote access without a login is refused at the HTTP edge (finding F2).
    monkeypatch.setattr(login, "get_credentials_hash", lambda: None)

    result, registered = connect("sid-local", None)

    assert result is True
    assert registered == ["sid-local"]

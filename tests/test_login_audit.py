"""The real sign-in and sign-out handlers write full audit records: request
details, the attempted username (never the password), and a login_id that ties
a sign-out to its sign-in."""

import asyncio
import json

import pytest
from flask import Flask

from helpers import access_control as ac
from helpers import ui_server

USER, PASSWORD = "owner", "correct horse"
REMOTE = {"CF-Connecting-IP": "203.0.113.50", "CF-Ray": "r1", "CF-IPCountry": "CA", "User-Agent": "UA-test"}


@pytest.fixture
def app(monkeypatch, tmp_path):
    log = tmp_path / "audit.jsonl"
    monkeypatch.setattr(ac, "_audit_path", lambda: str(log))
    from helpers import extension
    monkeypatch.setattr(extension, "_get_extension_classes", lambda *a, **k: [])
    monkeypatch.setattr(ac, "_ip_history", None)
    monkeypatch.setattr(ac, "_active_tunnel_provider", lambda: "cloudflared")
    monkeypatch.setattr(ac, "_current_policy", lambda: (True, ac.parse_allowlist("203.0.113.50")))
    monkeypatch.setattr(ac, "login_throttle", ac.LoginThrottle())
    monkeypatch.setattr(ui_server.dotenv, "get_dotenv_value", lambda k: {"AUTH_LOGIN": USER, "AUTH_PASSWORD": PASSWORD}.get(k))
    monkeypatch.setattr(ui_server.login, "get_credentials_hash", lambda: "hash")
    monkeypatch.setattr(ui_server.files, "read_file", lambda *a, **k: "{{ error or '' }}")
    monkeypatch.setattr(ui_server.asyncio, "sleep", lambda *_: asyncio.sleep(0))
    from helpers import notification
    monkeypatch.setattr(notification.NotificationManager, "send_notification", staticmethod(lambda **kw: None))

    flask_app = Flask(__name__)
    flask_app.secret_key = "test"
    handlers = ui_server.UiRouteHandlers(runtime_state=None)
    flask_app.add_url_rule("/login", "login_handler", handlers.login_handler, methods=["GET", "POST"])
    flask_app.add_url_rule("/logout", "logout_handler", handlers.logout_handler)
    flask_app.add_url_rule("/", "serve_index", lambda: "index")
    flask_app.log_path = log
    return flask_app


def _records(app):
    return [json.loads(l) for l in app.log_path.read_text(encoding="utf-8").splitlines()]


def test_failed_then_successful_sign_in_then_sign_out(app):
    client = app.test_client()
    client.post("/login", data={"username": USER, "password": "wrong"}, headers=REMOTE)
    client.post("/login", data={"username": USER, "password": PASSWORD}, headers=REMOTE)
    client.get("/logout", headers=REMOTE)

    failure, success, logout = _records(app)
    assert failure["event"] == "login_failure"
    assert failure["username"] == USER and failure["username_correct"] is True
    assert failure["failures_in_window"] == 1 and failure["locked"] is False
    assert failure["ip"] == "203.0.113.50" and failure["via"] == "tunnel:cloudflared"
    assert failure["country"] == "CA" and failure["user_agent"] == "UA-test" and failure["method"] == "POST"
    assert failure["ip_seen_before"] is False

    assert success["event"] == "login_success" and success["ip_seen_before"] is True
    assert len(success["login_id"]) == 16
    assert logout["event"] == "logout" and logout["login_id"] == success["login_id"]

    raw = app.log_path.read_text(encoding="utf-8")
    assert PASSWORD not in raw and "wrong" not in raw


def test_sign_out_without_a_session_is_not_logged(app):
    app.test_client().get("/logout", headers=REMOTE)
    assert not app.log_path.exists()

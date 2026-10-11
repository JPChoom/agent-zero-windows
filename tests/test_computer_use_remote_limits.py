"""Remote Computer Use keeps A0W's own limits (enforcement audit E10)."""

from __future__ import annotations

import asyncio
import types

import pytest

from helpers import kill_switch
from plugins._a0_connector.tools import computer_use_remote as remote


def _tool(args):
    agent = types.SimpleNamespace(context=types.SimpleNamespace(id="ctx"))
    return remote.ComputerUseRemote(agent, "computer_use_remote", None, args, "", None)


@pytest.fixture
def no_cli(monkeypatch):
    def unreachable(*a, **k):
        raise AssertionError("must not contact the CLI host")

    monkeypatch.setattr(remote, "select_computer_use_target_sid", unreachable)
    monkeypatch.setattr(kill_switch, "is_tripped", lambda: False)


@pytest.mark.parametrize("keys", ["super+l", "ctrl+alt+delete", ["ctrl", "shift", "esc"], "win+r"])
def test_blocked_key_combos_are_refused_locally(no_cli, keys):
    result = asyncio.run(_tool({"action": "key", "keys": keys}).execute())
    assert "blocked" in result.message


def test_kill_switch_stops_remote_input(no_cli, monkeypatch):
    monkeypatch.setattr(kill_switch, "is_tripped", lambda: True)
    monkeypatch.setattr(kill_switch, "denial_message", lambda: "KILL SWITCH")
    for action in ("click", "type", "key", "uia_action"):
        assert asyncio.run(_tool({"action": action, "keys": "enter", "text": "x"}).execute()).message == "KILL SWITCH"


def test_ordinary_keys_are_not_refused_locally():
    assert _tool({"action": "key", "keys": "ctrl+s"})._local_refusal("key") == ""
    assert _tool({"action": "capture"})._local_refusal("capture") == ""

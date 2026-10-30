"""Chat integrations keep their running loops across a plugin re-import.

A change to any bundled plugin's Python files purges every `plugins.*`
module. State kept in plugin module globals came back empty while the old
loops kept running, so the next job-loop tick started a second one: Telegram
then fought itself ("Conflict: terminated by other getUpdates request"),
email read each mailbox twice, WhatsApp started a second bridge.
(Telegram's own test is in test_telegram_webhook_secret.py.)
"""

import importlib
import sys

import pytest


def _registry(name):
    # the chat_channels module the plugins actually see (a test elsewhere may
    # have swapped it in sys.modules)
    return sys.modules["helpers.chat_channels"].registry(name)


def _reimport(name):
    """What helpers.modules.purge_namespace("plugins") does to one module."""
    sys.modules.pop(name, None)
    return importlib.import_module(name)


@pytest.fixture
def clean_registries():
    yield
    for name in ("email", "whatsapp"):
        _registry(name).clear()


def test_email_poll_loops_and_state_lock_survive(clean_registries):
    name = "plugins._email_integration.helpers.handler"
    before = _reimport(name)  # bound to the current chat_channels
    running = object()
    before._poll_tasks["inbox"] = running
    after = _reimport(name)
    assert after is not before
    assert after._poll_tasks["inbox"] is running
    assert after._state_lock is before._state_lock  # one lock around the state file


def test_whatsapp_poll_task_and_bridge_survive(clean_registries):
    handler_name = "plugins._whatsapp_integration.helpers.handler"
    bridge_name = "plugins._whatsapp_integration.helpers.bridge_manager"
    handler, bridge = _reimport(handler_name), _reimport(bridge_name)
    task, process = object(), object()
    handler.POLL["task"] = task
    bridge._bridge.process = process
    bridge._bridge.config.update({"port": 3100, "mode": "self-chat"})
    try:
        handler2, bridge2 = _reimport(handler_name), _reimport(bridge_name)
        assert handler2.POLL["task"] is task
        assert bridge2._bridge.process is process  # the Node bridge is still known
        assert bridge2.get_running_config() == {"port": 3100, "mode": "self-chat"}
    finally:
        bridge._bridge.process = None
        bridge._bridge.config.clear()

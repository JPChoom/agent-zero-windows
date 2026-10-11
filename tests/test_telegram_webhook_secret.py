"""Telegram webhook always needs the registered secret (investigation finding F7)."""

import asyncio
import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))




class _Any:
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return _Any()

    def __call__(self, *args, **kwargs):
        return _Any()


class _Update:
    @classmethod
    def model_validate(cls, data, context=None):
        return data


_AIOGRAM_NAMES = {
    "aiogram": ["Bot", "Dispatcher", "Router"],
    "aiogram.client": [],
    "aiogram.client.default": ["DefaultBotProperties"],
    "aiogram.enums": ["ParseMode", "ChatType", "ContentType"],
    "aiogram.filters": ["Command", "CommandStart"],
    "aiogram.types": ["BotCommand", "Message"],
}
_PLUGIN_MODULES = (
    "plugins._telegram_integration.helpers.bot_manager",
    "plugins._telegram_integration.api.webhook",
)


@pytest.fixture
def tg(monkeypatch):
    """The webhook handler and bot manager, importable without aiogram.

    The plugin installs aiogram on first use, so a clean test environment may
    not have it. A minimal stand-in is installed for this test only (and the
    plugin modules imported against it are dropped afterwards), so other
    tests that check for the real aiogram are not fooled.
    """
    import importlib

    try:
        import aiogram  # noqa: F401
        stubbed = False
    except ImportError:
        stubbed = True
        for module_name, attrs in _AIOGRAM_NAMES.items():
            module = types.ModuleType(module_name)
            for attr in attrs:
                setattr(module, attr, _Any)
            monkeypatch.setitem(sys.modules, module_name, module)
        sys.modules["aiogram"].F = _Any()
        sys.modules["aiogram.types"].Update = _Update
        for name in _PLUGIN_MODULES:
            monkeypatch.delitem(sys.modules, name, raising=False)

    bot_manager = importlib.import_module(_PLUGIN_MODULES[0])
    webhook_api = importlib.import_module(_PLUGIN_MODULES[1])
    yield types.SimpleNamespace(bot_manager=bot_manager, webhook_api=webhook_api)
    if stubbed:
        for name in _PLUGIN_MODULES:
            sys.modules.pop(name, None)


class FakeBot:
    def __init__(self):
        self.registered = None

    async def set_webhook(self, url, secret_token=None):
        self.registered = {"url": url, "secret_token": secret_token}


class FakeDispatcher:
    def __init__(self):
        self.fed = []

    async def feed_update(self, bot, update):
        self.fed.append(update)


def _instance(secret=""):
    return types.SimpleNamespace(
        name="main", bot=FakeBot(), dispatcher=FakeDispatcher(),
        webhook_active=bool(secret), webhook_secret=secret,
    )


def _post(tg, instance, monkeypatch, header=None):
    webhook_api, bot_manager = tg.webhook_api, tg.bot_manager
    monkeypatch.setattr(webhook_api, "ensure_dependencies", lambda: None)
    monkeypatch.setattr(bot_manager, "get_bot", lambda name: instance if name == "main" else None)
    headers = {} if header is None else {"X-Telegram-Bot-Api-Secret-Token": header}
    request = types.SimpleNamespace(args={"bot": "main"}, headers=headers)
    update = {"update_id": 1}
    handler = webhook_api.TelegramWebhook(app=None, thread_lock=None)
    return asyncio.run(handler.process(update, request))


def test_setup_generates_a_secret_when_none_is_configured(tg):
    instance = _instance()
    asyncio.run(tg.bot_manager.setup_webhook(instance, "https://example.com", ""))
    secret = instance.bot.registered["secret_token"]
    assert secret and len(secret) >= 32
    assert set(secret) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")
    assert instance.webhook_secret == secret


def test_setup_keeps_a_configured_secret(tg):
    instance = _instance()
    asyncio.run(tg.bot_manager.setup_webhook(instance, "https://example.com", "configured_secret"))
    assert instance.bot.registered["secret_token"] == "configured_secret"


def test_request_without_secret_is_refused(tg, monkeypatch):
    instance = _instance("s3cret")
    result = _post(tg, instance, monkeypatch, header=None)
    assert getattr(result, "status_code", None) == 403
    assert instance.dispatcher.fed == []


def test_request_with_wrong_secret_is_refused(tg, monkeypatch):
    instance = _instance("s3cret")
    result = _post(tg, instance, monkeypatch, header="guess")
    assert getattr(result, "status_code", None) == 403
    assert instance.dispatcher.fed == []


def test_bot_without_active_secret_accepts_nothing(tg, monkeypatch):
    # Not in webhook mode (e.g. polling): an empty secret must not mean "open".
    instance = _instance("")
    result = _post(tg, instance, monkeypatch, header="")
    assert getattr(result, "status_code", None) == 403
    assert instance.dispatcher.fed == []

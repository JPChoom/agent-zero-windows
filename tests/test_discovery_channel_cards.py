"""Welcome-screen "Connect Channels" cards: one per built-in channel, hidden once configured."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "plugins" / "_discovery" / "extensions" / "python" / "banners" / "10_discovery_cards.py"

CHANNELS = {
    "discovery-telegram": "_telegram_integration",
    "discovery-email": "_email_integration",
    "discovery-whatsapp": "_whatsapp_integration",
    "discovery-discord": "_discord_integration",
    "discovery-slack": "_slack_integration",
}


def _cards(monkeypatch, configs: dict) -> dict:
    spec = importlib.util.spec_from_file_location("discovery_cards_under_test", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.plugins, "get_plugin_config", lambda name, *a, **k: configs.get(name, {}))
    monkeypatch.setattr(module.DiscoveryCardsExtension, "_oauth_summary", lambda self: {})
    banners: list = []
    asyncio.run(module.DiscoveryCardsExtension(agent=None).execute(banners=banners))
    return {b["id"]: b for b in banners if b.get("type") == "feature"}


def test_every_builtin_channel_gets_a_card_when_nothing_is_configured(monkeypatch):
    cards = _cards(monkeypatch, {})
    assert set(cards) == set(CHANNELS)
    for card_id, plugin in CHANNELS.items():
        assert cards[card_id]["cta_action"] == f"open-plugin-config:{plugin}"
        assert cards[card_id]["show_in_onboarding"] is True


def test_discord_and_slack_cards_use_an_icon_when_they_have_no_thumbnail(monkeypatch):
    cards = _cards(monkeypatch, {})
    for card_id in ("discovery-discord", "discovery-slack"):
        assert cards[card_id]["icon"] and "thumbnail" not in cards[card_id]


def test_discord_card_disappears_once_a_bot_token_is_set(monkeypatch):
    configs = {"_discord_integration": {"bots": [{"name": "a0", "token": "set"}]}}
    assert "discovery-discord" not in _cards(monkeypatch, configs)
    assert "discovery-discord" in _cards(monkeypatch, {"_discord_integration": {"bots": [{"name": "a0", "token": ""}]}})


@pytest.mark.parametrize("bot,hidden", [
    ({"bot_token": "set", "app_token": "set"}, True),
    ({"bot_token": "set", "app_token": ""}, False),
    ({"bot_token": "", "app_token": "set"}, False),
])
def test_slack_card_needs_both_tokens_to_count_as_configured(monkeypatch, bot, hidden):
    cards = _cards(monkeypatch, {"_slack_integration": {"bots": [bot]}})
    assert ("discovery-slack" not in cards) is hidden


def test_other_channels_are_unaffected_by_discord_and_slack_setup(monkeypatch):
    configs = {
        "_discord_integration": {"bots": [{"token": "set"}]},
        "_slack_integration": {"bots": [{"bot_token": "set", "app_token": "set"}]},
    }
    assert set(_cards(monkeypatch, configs)) == {"discovery-telegram", "discovery-email", "discovery-whatsapp"}

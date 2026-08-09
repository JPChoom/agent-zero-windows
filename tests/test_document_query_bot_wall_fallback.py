"""Tests for document_query's bot-wall detection and browser-fallback fetch.

Live-verified separately (not automatable in CI - needs a real network
call and a real Chromium instance) against the exact URL from a user-
reported failure: fetch_public_resource() on a reddit.com post permalink
returned only 6 chars of visible text ("Reddit") via plain aiohttp, and
16,452 chars of real post/comment content once routed through the
internal browser fallback added here.

These tests cover the deterministic, mockable pieces: the bot-wall
heuristic itself, and the fallback's graceful-degradation contract (must
never raise, must return None on any failure).
"""

from __future__ import annotations

import asyncio

import pytest

from plugins._document_query.helpers.fetch import (
    _fetch_via_browser,
    _looks_like_bot_wall,
    _visible_text_from_html,
)


def run_async(coro):
    with asyncio.Runner() as runner:
        return runner.run(coro)


# ------------------------------------------------------------------
# _visible_text_from_html
# ------------------------------------------------------------------

def test_visible_text_from_html_strips_tags_scripts_and_styles():
    html = """
    <html><head><style>body { color: red; }</style>
    <script>console.log("noise");</script></head>
    <body><h1>Real Title</h1><p>Real paragraph content here.</p></body></html>
    """
    visible = _visible_text_from_html(html)
    assert "Real Title" in visible
    assert "Real paragraph content here." in visible
    assert "console.log" not in visible
    assert "color: red" not in visible


def test_visible_text_from_html_collapses_whitespace():
    html = "<p>a</p>\n\n\n<p>   b   </p>"
    assert _visible_text_from_html(html) == "a b"


# ------------------------------------------------------------------
# _looks_like_bot_wall
# ------------------------------------------------------------------

def test_bot_wall_detects_short_visible_text_like_reddit_challenge_shell():
    # Reproduces the actual shape of the page reddit.com serves to a plain
    # aiohttp GET: several KB of JS/CSS boilerplate, ~6 chars of visible text.
    html = (
        "<html><head><title>Reddit</title>"
        "<script>" + ("x = 1; " * 500) + "</script></head>"
        "<body></body></html>"
    )
    assert _looks_like_bot_wall(html) is True


def test_bot_wall_detects_explicit_challenge_marker_regardless_of_length():
    html = "<html><body>" + ("Please wait. " * 100) + "Prove your humanity.</body></html>"
    assert _looks_like_bot_wall(html) is True


def test_bot_wall_does_not_flag_a_real_article_page():
    html = (
        "<html><body><h1>A Real Article Title</h1>"
        + "<p>" + ("This is real paragraph content about the article topic. " * 20) + "</p>"
        + "</body></html>"
    )
    assert _looks_like_bot_wall(html) is False


def test_bot_wall_treats_empty_text_as_not_a_bot_wall():
    # Nothing to fall back and retry for - let the caller's own empty/
    # missing-content handling take over instead of trying the browser too.
    assert _looks_like_bot_wall("") is False
    assert _looks_like_bot_wall("   ") is False


# ------------------------------------------------------------------
# _fetch_via_browser: must never raise, must degrade to None
# ------------------------------------------------------------------

def test_fetch_via_browser_returns_none_when_runtime_unavailable(monkeypatch):
    from plugins._browser.helpers import runtime as browser_runtime

    async def _fake_get_runtime(context_id, create=True):
        return None

    monkeypatch.setattr(browser_runtime, "get_runtime", _fake_get_runtime)

    result = run_async(_fetch_via_browser("https://example.com/blocked"))
    assert result is None


def test_fetch_via_browser_returns_none_on_any_exception(monkeypatch):
    from plugins._browser.helpers import runtime as browser_runtime

    async def _raises(*args, **kwargs):
        raise RuntimeError("simulated browser failure")

    monkeypatch.setattr(browser_runtime, "get_runtime", _raises)

    result = run_async(_fetch_via_browser("https://example.com/blocked"))
    assert result is None


def test_fetch_via_browser_returns_document_with_extracted_text(monkeypatch):
    from plugins._browser.helpers import runtime as browser_runtime

    class _FakeRuntime:
        async def call(self, action, *args, **kwargs):
            if action == "open":
                return {"ok": True}
            if action == "content":
                return {"document": "Real extracted post content here."}
            raise AssertionError(f"unexpected action {action}")

    async def _fake_get_runtime(context_id, create=True):
        return _FakeRuntime()

    async def _fake_close_runtime(context_id, delete_profile=True):
        return None

    real_sleep = asyncio.sleep
    monkeypatch.setattr(browser_runtime, "get_runtime", _fake_get_runtime)
    monkeypatch.setattr(browser_runtime, "close_runtime", _fake_close_runtime)
    monkeypatch.setattr(asyncio, "sleep", lambda *_: real_sleep(0))

    result = run_async(_fetch_via_browser("https://example.com/post"))
    assert result is not None
    assert result.mimetype == "text/plain"
    assert "Real extracted post content here." in result.text()

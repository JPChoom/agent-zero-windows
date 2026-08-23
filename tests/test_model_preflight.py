"""Tests for plugins/_model_config/helpers/preflight.py.

Preflight compares Agent Zero's configured model slots against what the
local inference server reports it actually has loaded. Motivated by two
real, expensive-to-diagnose incidents in this fork:

  * ctx_length set well below the model's loaded capacity, starving it of
    room to reason and emit a tool call in the same turn - produced a chat
    that generated megabytes of output with zero tool calls.
  * A configured model that the server doesn't have, surfacing much later
    as an opaque provider-side load failure.

The network-facing parts are exercised through a stubbed httpx client;
the comparison logic is pure and tested directly.
"""

from __future__ import annotations

import pytest

from plugins._model_config.helpers import preflight


# ------------------------------------------------------------------
# URL construction
# ------------------------------------------------------------------

def test_runtime_info_url_strips_openai_v1_suffix():
    # api_base points at the OpenAI-compatible surface, but the REST API
    # that reports context lengths lives at the server root.
    assert (
        preflight.runtime_info_url("http://127.0.0.1:1234/v1")
        == "http://127.0.0.1:1234/api/v0/models"
    )


def test_runtime_info_url_handles_trailing_slash_and_bare_base():
    assert (
        preflight.runtime_info_url("http://127.0.0.1:1234/v1/")
        == "http://127.0.0.1:1234/api/v0/models"
    )
    assert (
        preflight.runtime_info_url("http://127.0.0.1:1234")
        == "http://127.0.0.1:1234/api/v0/models"
    )


def test_runtime_info_url_empty_base_yields_nothing():
    assert preflight.runtime_info_url("") == ""
    assert preflight.runtime_info_url("   ") == ""


# ------------------------------------------------------------------
# check_slot - the comparison logic
# ------------------------------------------------------------------

LOADED = {
    "qwen/qwen3.8-27b": {
        "state": "loaded",
        "loaded_context_length": 65536,
        "max_context_length": 262144,
    }
}


def test_matching_context_produces_no_findings():
    findings = preflight.check_slot(
        "Chat", {"name": "qwen/qwen3.8-27b", "ctx_length": 65536}, LOADED
    )
    assert findings == []


def test_configured_context_above_loaded_is_a_warning():
    findings = preflight.check_slot(
        "Chat", {"name": "qwen/qwen3.8-27b", "ctx_length": 131072}, LOADED
    )
    assert len(findings) == 1
    assert findings[0]["level"] == "warning"
    # Should mention both numbers and the available headroom.
    assert "131,072" in findings[0]["detail"]
    assert "65,536" in findings[0]["detail"]
    assert "262,144" in findings[0]["detail"]


def test_configured_context_below_loaded_is_informational():
    """The exact shape of the live incident: plenty of server capacity,
    Agent Zero configured far below it."""
    findings = preflight.check_slot(
        "Utility", {"name": "qwen/qwen3.8-27b", "ctx_length": 16384}, LOADED
    )
    assert len(findings) == 1
    assert findings[0]["level"] == "info"
    assert "16,384" in findings[0]["detail"]
    assert "65,536" in findings[0]["detail"]


def test_model_missing_from_server_is_a_warning():
    findings = preflight.check_slot(
        "Chat", {"name": "some-renamed-model", "ctx_length": 8192}, LOADED
    )
    assert len(findings) == 1
    assert findings[0]["level"] == "warning"
    assert "not found" in findings[0]["title"].lower()


def test_unloaded_model_does_not_warn_about_context():
    """LM Studio JIT-loads on first use and reports null context until
    then - that's normal, not a misconfiguration."""
    server = {
        "some-model": {
            "state": "not-loaded",
            "loaded_context_length": None,
            "max_context_length": 32768,
        }
    }
    findings = preflight.check_slot(
        "Chat", {"name": "some-model", "ctx_length": 8192}, server
    )
    assert findings == []


def test_slot_without_a_name_is_skipped():
    assert preflight.check_slot("Chat", {"name": "", "ctx_length": 1000}, LOADED) == []
    assert preflight.check_slot("Chat", {}, LOADED) == []


def test_non_dict_slot_is_skipped():
    assert preflight.check_slot("Chat", None, LOADED) == []  # type: ignore[arg-type]


# ------------------------------------------------------------------
# fetch_server_models - network-facing, must fail soft
# ------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code=200, payload=None, raises=False):
        self.status_code = status_code
        self._payload = payload
        self._raises = raises

    def json(self):
        if self._raises:
            raise ValueError("not json")
        return self._payload


class _FakeClient:
    def __init__(self, response=None, raises=None):
        self._response = response
        self._raises = raises

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        if self._raises:
            raise self._raises
        return self._response


def _patch_client(monkeypatch, client):
    monkeypatch.setattr(preflight.httpx, "AsyncClient", lambda **kw: client)


@pytest.mark.asyncio
async def test_unsupported_provider_makes_no_request(monkeypatch):
    def _boom(**kwargs):
        raise AssertionError("should not have issued a request")

    monkeypatch.setattr(preflight.httpx, "AsyncClient", _boom)
    assert await preflight.fetch_server_models("ollama", "http://x/v1") == {}


@pytest.mark.asyncio
async def test_parses_a_well_formed_response(monkeypatch):
    payload = {
        "data": [
            {
                "id": "qwen/qwen3.8-27b",
                "state": "loaded",
                "loaded_context_length": 65536,
                "max_context_length": 262144,
            },
            {"id": "other", "state": "not-loaded"},
        ]
    }
    _patch_client(monkeypatch, _FakeClient(_FakeResponse(payload=payload)))

    result = await preflight.fetch_server_models("lm_studio", "http://127.0.0.1:1234/v1")

    assert result["qwen/qwen3.8-27b"]["loaded_context_length"] == 65536
    assert result["other"]["state"] == "not-loaded"


@pytest.mark.asyncio
async def test_unreachable_server_returns_empty(monkeypatch):
    _patch_client(monkeypatch, _FakeClient(raises=OSError("connection refused")))
    assert await preflight.fetch_server_models("lm_studio", "http://127.0.0.1:1234/v1") == {}


@pytest.mark.asyncio
async def test_non_200_returns_empty(monkeypatch):
    _patch_client(monkeypatch, _FakeClient(_FakeResponse(status_code=404)))
    assert await preflight.fetch_server_models("lm_studio", "http://127.0.0.1:1234/v1") == {}


@pytest.mark.asyncio
async def test_malformed_json_returns_empty(monkeypatch):
    _patch_client(monkeypatch, _FakeClient(_FakeResponse(raises=True)))
    assert await preflight.fetch_server_models("lm_studio", "http://127.0.0.1:1234/v1") == {}


@pytest.mark.asyncio
async def test_unexpected_payload_shape_returns_empty(monkeypatch):
    _patch_client(monkeypatch, _FakeClient(_FakeResponse(payload=["not", "a", "dict"])))
    assert await preflight.fetch_server_models("lm_studio", "http://127.0.0.1:1234/v1") == {}


# ------------------------------------------------------------------
# run_preflight - end to end over a config
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_preflight_queries_each_server_once(monkeypatch):
    """Three slots on one local server must cost one request, not three."""
    calls = []

    async def fake_fetch(provider, api_base):
        calls.append((provider, api_base))
        return LOADED

    monkeypatch.setattr(preflight, "fetch_server_models", fake_fetch)

    config = {
        "chat_model": {
            "provider": "lm_studio",
            "name": "qwen/qwen3.8-27b",
            "api_base": "http://127.0.0.1:1234/v1",
            "ctx_length": 65536,
        },
        "utility_model": {
            "provider": "lm_studio",
            "name": "qwen/qwen3.8-27b",
            "api_base": "http://127.0.0.1:1234/v1",
            "ctx_length": 16384,
        },
        # Non-local provider must be skipped entirely.
        "embedding_model": {
            "provider": "huggingface",
            "name": "sentence-transformers/all-MiniLM-L6-v2",
            "api_base": "",
        },
    }

    findings = await preflight.run_preflight(config)

    assert len(calls) == 1
    # Only the utility slot is misconfigured (16k vs 65k loaded).
    assert len(findings) == 1
    assert findings[0]["level"] == "info"
    assert "Utility" in findings[0]["title"]


@pytest.mark.asyncio
async def test_run_preflight_silent_when_server_unreachable(monkeypatch):
    async def fake_fetch(provider, api_base):
        return {}

    monkeypatch.setattr(preflight, "fetch_server_models", fake_fetch)

    config = {
        "chat_model": {
            "provider": "lm_studio",
            "name": "whatever",
            "api_base": "http://127.0.0.1:1234/v1",
            "ctx_length": 99999,
        }
    }

    assert await preflight.run_preflight(config) == []

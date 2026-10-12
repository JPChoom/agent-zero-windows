"""Context-window safety: the real server window, trimming extras, and
recovering from an overflow (helpers/prompt_budget, agent.prepare_prompt,
plugins/_error_retry)."""

from __future__ import annotations

import asyncio
import types

import pytest

from helpers import prompt_budget, tokens


@pytest.fixture(autouse=True)
def _no_cache():
    prompt_budget._cache.clear()
    yield
    prompt_budget._cache.clear()


# -- the window the server really has -----------------------------------------

def test_lm_studio_reported_window_wins_when_smaller(monkeypatch):
    monkeypatch.setattr(prompt_budget, "_get_json", lambda url: {"data": [
        {"id": "qwen", "state": "loaded", "loaded_context_length": 16384}]})
    cfg = {"provider": "lm_studio", "name": "qwen", "ctx_length": 32768}
    assert prompt_budget.effective_ctx_length(cfg) == 16384


def test_configured_window_wins_when_smaller(monkeypatch):
    monkeypatch.setattr(prompt_budget, "_get_json", lambda url: {"data": [
        {"id": "qwen", "state": "loaded", "loaded_context_length": 49152}]})
    cfg = {"provider": "lm_studio", "name": "qwen", "ctx_length": 32768}
    assert prompt_budget.effective_ctx_length(cfg) == 32768


def test_llama_cpp_reports_n_ctx(monkeypatch):
    seen = []

    def fake(url):
        seen.append(url)
        return {"default_generation_settings": {"n_ctx": 8192}}

    monkeypatch.setattr(prompt_budget, "_get_json", fake)
    cfg = {"provider": "llama_cpp", "name": "m", "ctx_length": 32768}
    assert prompt_budget.effective_ctx_length(cfg) == 8192
    assert seen == ["http://127.0.0.1:8090/props"]


def test_unreachable_server_falls_back_to_the_configured_window(monkeypatch):
    def down(url):
        raise OSError("connection refused")

    monkeypatch.setattr(prompt_budget, "_get_json", down)
    assert prompt_budget.effective_ctx_length({"provider": "lm_studio", "name": "q", "ctx_length": 32768}) == 32768


def test_cloud_providers_are_never_queried(monkeypatch):
    monkeypatch.setattr(prompt_budget, "_get_json", lambda url: pytest.fail("must not query"))
    assert prompt_budget.effective_ctx_length({"provider": "anthropic", "name": "x", "ctx_length": 200000}) == 200000


def test_detection_is_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(prompt_budget, "_get_json", lambda url: calls.append(url) or {"data": []})
    cfg = {"provider": "lm_studio", "name": "q", "ctx_length": 32768}
    for _ in range(5):
        prompt_budget.effective_ctx_length(cfg)
    assert len(calls) == 1


def test_docker_era_host_is_treated_as_this_pc():
    assert prompt_budget._server_root({"provider": "lm_studio", "api_base": "http://host.docker.internal:1234/v1"}) == "http://127.0.0.1:1234"


# -- overflow factor ------------------------------------------------------------

def _agent():
    data = {}
    return types.SimpleNamespace(get_data=data.get, set_data=data.__setitem__, data=data)


def test_overflow_shrinks_the_window_down_to_half():
    agent = _agent()
    cfg = {"provider": "openai", "ctx_length": 40000}
    assert prompt_budget.effective_ctx_length(cfg, agent) == 40000
    prompt_budget.shrink_after_overflow(agent)
    assert prompt_budget.effective_ctx_length(cfg, agent) == 34000
    for _ in range(20):
        prompt_budget.shrink_after_overflow(agent)
    assert prompt_budget.effective_ctx_length(cfg, agent) == 20000


@pytest.mark.parametrize("text,expected", [
    ('{"code":500,"message":"Context size has been exceeded."}', True),
    ("request (128707 tokens) exceeds the available context size", True),
    ("This model's maximum context length is 8192 tokens", True),
    ("Error code: context_length_exceeded", True),
    ("Rate limit: too many tokens per minute", False),
    ("Model unloaded by user or API request", False),
])
def test_overflow_errors_are_recognised(text, expected):
    assert prompt_budget.is_context_overflow(text) is expected


# -- trimming extras --------------------------------------------------------------

def _extras():
    return {
        "current_datetime": "2026-10-11 10:00",
        "memories": "memory " * 600,
        "solutions": "solution " * 900,
        "relevant_skills": "skill " * 400,
        "project_file_structure": "file " * 300,
        "agent_info": "A0",
    }


def test_shrinking_shortens_recall_first_and_never_touches_essentials():
    extras = _extras()
    small, changed = prompt_budget.shrink_extras(extras, 500)
    assert changed and changed[0] == "shortened solutions"
    assert small["current_datetime"] == extras["current_datetime"] and small["agent_info"] == "A0"
    assert "solutions" in small and "relevant_skills" in small
    assert extras["solutions"] == "solution " * 900  # input untouched (persistent extras stay)


def test_large_excess_drops_extras_in_order():
    small, changed = prompt_budget.shrink_extras(_extras(), 100000)
    assert set(small) == {"current_datetime", "agent_info"}
    assert changed[-1] == "left out memories" or "left out memories" in changed


def test_no_excess_changes_nothing():
    extras = _extras()
    small, changed = prompt_budget.shrink_extras(extras, 0)
    assert small == extras and changed == []


# -- the agent trims extras before the prompt goes out ------------------------------

def test_agent_trims_extras_when_the_fixed_part_is_too_big(monkeypatch):
    import agent as agent_module

    fake = types.SimpleNamespace(context=types.SimpleNamespace(log=types.SimpleNamespace(log=lambda **k: None)))
    fake._window_and_reserve = lambda: (8000, 2000)
    system = "s " * 2000  # ~2200 tokens
    extras = _extras()
    result = agent_module.Agent._fit_extras_to_window(fake, system, [], extras)
    total = tokens.approximate_prompt_tokens(system) + sum(tokens.approximate_prompt_tokens(str(v)) for v in result.values())
    assert total + 2000 + int(8000 * 0.2) <= 8000 + 200  # fits (within trimming slack)
    assert "current_datetime" in result


def test_agent_leaves_extras_alone_when_they_fit():
    import agent as agent_module

    fake = types.SimpleNamespace(context=None)
    fake._window_and_reserve = lambda: (100000, 25000)
    extras = _extras()
    assert agent_module.Agent._fit_extras_to_window(fake, "short system", [], extras) is extras


# -- recovering from an overflow ---------------------------------------------------

def test_overflow_error_is_retried_with_less_context(monkeypatch):
    from plugins._error_retry.extensions.python._functions.agent.Agent.handle_exception.end import (
        _80_retry_critical_exception as retry,
    )

    data_store = {}
    warnings = []
    compressed = []

    async def compress():
        compressed.append(True)

    agent = types.SimpleNamespace(
        get_data=data_store.get, set_data=data_store.__setitem__, data=data_store,
        history=types.SimpleNamespace(compress=compress),
        context=types.SimpleNamespace(log=types.SimpleNamespace(log=lambda **k: None)),
        hist_add_warning=lambda message, **k: warnings.append(message),
    )
    ext = retry.RetryCriticalException(agent=agent)
    for attempt in range(retry.MAX_OVERFLOW_RETRIES):
        payload = {"exception": RuntimeError('{"code":500,"message":"Context size has been exceeded."}')}
        assert asyncio.run(ext._recover_from_overflow(payload, payload["exception"])) is True
        assert payload["exception"] is None
    assert len(compressed) == retry.MAX_OVERFLOW_RETRIES
    assert prompt_budget.overflow_factor(agent) < 1.0
    assert all(len(w) < 400 for w in warnings)  # a short note, not the long error text
    # After the retries are used up it falls through to the normal handling.
    payload = {"exception": RuntimeError("Context size has been exceeded.")}
    assert asyncio.run(ext._recover_from_overflow(payload, payload["exception"])) is False


def test_other_errors_are_not_treated_as_overflow():
    from plugins._error_retry.extensions.python._functions.agent.Agent.handle_exception.end import (
        _80_retry_critical_exception as retry,
    )

    agent = _agent()
    ext = retry.RetryCriticalException(agent=agent)
    payload = {"exception": RuntimeError("Model unloaded by user or API request")}
    assert asyncio.run(ext._recover_from_overflow(payload, payload["exception"])) is False

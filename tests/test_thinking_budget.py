"""Thinking budget for the Main model (plugins/_model_config/helpers/thinking.py)."""

import asyncio
import types

import pytest

from plugins._model_config.helpers import thinking


@pytest.mark.parametrize("cfg,expected", [
    ({}, "on"), ({"thinking": "off"}, "off"), ({"thinking": "AUTO"}, "auto"), ({"thinking": "bogus"}, "on"),
])
def test_mode_reads_the_setting_and_defaults_to_on(cfg, expected):
    assert thinking.mode(cfg) == expected


def test_on_and_off_ignore_the_step():
    for iteration in (0, 1, 7):
        assert thinking.should_think("on", iteration, "") is True
        assert thinking.should_think("off", iteration, "Traceback (most recent call last)") is False


def test_auto_thinks_when_planning_and_after_trouble_only():
    assert thinking.should_think("auto", 0, "") is True  # first step of a turn
    assert thinking.should_think("auto", 3, '{"tool_result": "report.txt written 1 lines"}') is False
    for trouble in ("Error: file not found", "[safety_policy] Denied: ...", "Traceback (most recent call last):",
                    "You have misformatted your message.", "Command timed out after 60 s", "Permission denied"):
        assert thinking.should_think("auto", 3, trouble) is True, trouble


@pytest.mark.parametrize("provider,expected", [
    ("llama_cpp", {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}),
    ("lm_studio", {"a0_api_mode": "chat_completions", "extra_body": {"reasoning_effort": "none"}}),
    ("openai", {}),
])
def test_provider_specific_switch(provider, expected):
    assert thinking.no_thinking_kwargs(provider) == expected


def test_apply_merges_without_dropping_existing_extra_body():
    model = types.SimpleNamespace(kwargs={"extra_body": {"top_k": 20, "chat_template_kwargs": {"x": 1}}, "temperature": 0.6})
    assert thinking.apply(model, "llama_cpp") is True
    assert model.kwargs["extra_body"] == {"top_k": 20, "chat_template_kwargs": {"x": 1, "enable_thinking": False}}
    assert model.kwargs["temperature"] == 0.6
    other = types.SimpleNamespace(kwargs={})
    assert thinking.apply(other, "openai") is False and other.kwargs == {}


def _agent(iteration, last_text):
    message = types.SimpleNamespace(output_text=lambda: last_text)
    agent = types.SimpleNamespace(
        loop_data=types.SimpleNamespace(iteration=iteration),
        history=types.SimpleNamespace(current=types.SimpleNamespace(messages=[message])),
        _data={},
    )
    agent.set_data = lambda k, v: agent._data.__setitem__(k, v)
    agent.get_data = lambda k: agent._data.get(k)
    return agent


def _run(monkeypatch, mode, iteration, last_text, provider="llama_cpp"):
    from plugins._model_config.extensions.python.chat_model_call_before import _25_thinking as ext
    from plugins._model_config.helpers import model_config

    monkeypatch.setattr(model_config, "get_config", lambda agent=None: {"thinking": mode})
    agent = _agent(iteration, last_text)
    model = types.SimpleNamespace(kwargs={}, provider=provider, a0_model_conf=types.SimpleNamespace(provider=provider))
    hook = ext.ThinkingBudget(agent=agent)
    asyncio.run(hook.execute(call_data={"model": model}))
    return model, agent


def test_hook_leaves_on_untouched(monkeypatch):
    model, agent = _run(monkeypatch, "on", 4, "ok")
    assert model.kwargs == {} and agent.get_data(thinking.LAST_DECISION_KEY) is None


def test_hook_turns_thinking_off_on_a_routine_step_in_auto(monkeypatch):
    model, agent = _run(monkeypatch, "auto", 4, '{"tool_result": "done"}')
    assert model.kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
    assert agent.get_data(thinking.LAST_DECISION_KEY)["think"] is False


def test_hook_keeps_thinking_on_the_first_step_and_after_an_error(monkeypatch):
    for iteration, text in ((0, ""), (5, "Error: no such file")):
        model, agent = _run(monkeypatch, "auto", iteration, text)
        assert model.kwargs == {}
        assert agent.get_data(thinking.LAST_DECISION_KEY)["think"] is True


def test_off_on_an_unsupported_provider_is_recorded_as_thinking(monkeypatch):
    model, agent = _run(monkeypatch, "off", 3, "", provider="openai")
    assert model.kwargs == {} and agent.get_data(thinking.LAST_DECISION_KEY)["think"] is True


def test_settings_page_offers_the_modes_and_marks_auto_experimental():
    from pathlib import Path

    html = Path("plugins/_model_config/webui/config.html").read_text(encoding="utf-8")
    assert '<option value="auto">Auto (Experimental)</option>' in html
    assert "Experimental feature" in html.split('<option value="auto">')[0].rsplit("<select", 1)[1]

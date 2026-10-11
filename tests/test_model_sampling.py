"""Single-model mode, sampling presets and the EXPERIMENTAL dynamic sampling
(plugins/_model_config, v1.4 item 3)."""

from __future__ import annotations

import asyncio
import types

import pytest

from plugins._model_config import hooks
from plugins._model_config.helpers import dynamic_sampling, model_config


def _config(**overrides):
    base = {
        "chat_model": {"provider": "llama_cpp", "name": "qwen", "ctx_length": 32000, "kwargs": {}, "vision": True},
        "utility_model": {"provider": "lm_studio", "name": "small", "ctx_length": 8000, "ctx_input": 0.7, "kwargs": {}},
        "vision_model": {"provider": "lm_studio", "name": "llava"},
        "single_model_mode": False,
        "sampling": {},
    }
    base.update(overrides)
    return base


@pytest.fixture
def cfg(monkeypatch):
    holder = {"value": _config()}
    monkeypatch.setattr(model_config, "get_config", lambda agent=None, **k: holder["value"])
    monkeypatch.setattr(model_config, "_resolve_override", lambda agent: None)
    return holder


# -- single-model mode -----------------------------------------------------------

def test_single_model_mode_uses_the_main_model_for_utility(cfg):
    cfg["value"] = _config(single_model_mode=True)
    utility = model_config.get_utility_model_config()
    assert (utility["provider"], utility["name"], utility["ctx_length"]) == ("llama_cpp", "qwen", 32000)
    assert utility["ctx_input"] == 0.7  # the utility slot keeps its own share


def test_single_model_mode_has_no_separate_vision_sidecar(cfg):
    assert model_config.is_vision_model_configured() is True
    cfg["value"] = _config(single_model_mode=True)
    assert model_config.is_vision_model_configured() is False


def test_off_keeps_independent_slots(cfg):
    assert model_config.get_utility_model_config()["name"] == "small"


def test_saved_configs_gain_the_new_keys():
    restored = hooks.get_plugin_config(default={"chat_model": {}})
    assert "single_model_mode" in restored and "sampling" in restored and "vision_model" in restored
    assert restored["single_model_mode"] is False


# -- sampling presets ------------------------------------------------------------

def test_local_servers_get_every_sampling_value():
    out = model_config.sampling_kwargs({"temperature": 0.4, "top_p": 0.9, "top_k": 40, "repeat_penalty": 1.1}, "llama_cpp")
    assert out == {"temperature": 0.4, "top_p": 0.9, "extra_body": {"top_k": 40, "repeat_penalty": 1.1}}


def test_cloud_providers_only_get_standard_values():
    out = model_config.sampling_kwargs({"temperature": 0.4, "top_k": 40, "repeat_penalty": 1.1}, "anthropic")
    assert out == {"temperature": 0.4}


def test_unset_values_are_left_to_the_provider():
    assert model_config.sampling_kwargs({"temperature": None, "top_p": ""}, "llama_cpp") == {}


def test_a_models_own_kwargs_win_over_the_preset():
    slot = {"provider": "llama_cpp", "kwargs": {"temperature": 0.1, "extra_body": {"top_k": 5}}}
    merged = model_config.apply_sampling(slot, {"temperature": 0.9, "top_k": 50, "repeat_penalty": 1.2})
    assert merged["kwargs"]["temperature"] == 0.1
    assert merged["kwargs"]["extra_body"] == {"top_k": 5, "repeat_penalty": 1.2}
    assert slot["kwargs"] == {"temperature": 0.1, "extra_body": {"top_k": 5}}  # input not mutated


# -- experimental dynamic sampling ----------------------------------------------

RULES = {
    "code_tools": ["code_execution_tool", "text_editor"],
    "creative_words": ["story", "poem"],
    "offsets": {"code": {"temperature": -0.3, "top_p": -0.02, "repeat_penalty": 0.1},
                "creative": {"temperature": 0.3, "repeat_penalty": 0.4}, "reasoning": {}},
    "base": {"temperature": 0.6, "top_p": 0.95, "repeat_penalty": 1.0},
}


@pytest.mark.parametrize("tools,text,expected", [
    (["search_engine", "text_editor"], "fix the bug", "code"),
    ([], "write me a short story about rain", "creative"),
    (["search_engine"], "compare these two laptops", "reasoning"),
    ([], "a historical overview", "reasoning"),  # 'story' only as a whole word
])
def test_classification(tools, text, expected):
    assert dynamic_sampling.classify(tools, text, RULES) == expected


def test_offsets_apply_to_unlocked_values_only():
    sampling = {"temperature": 0.7, "locks": {"top_p": True}, "dynamic_rules": RULES}
    values = dynamic_sampling.adjusted_values(sampling, "code")
    assert values == {"temperature": 0.4, "repeat_penalty": 1.1}  # top_p locked, temperature from the preset


def test_reasoning_changes_nothing():
    assert dynamic_sampling.adjusted_values({"dynamic_rules": RULES}, "reasoning") == {}


def test_values_stay_in_range():
    sampling = {"temperature": 1.9, "top_p": 0.99, "dynamic_rules": {**RULES, "offsets": {"creative": {"temperature": 0.5, "top_p": 0.5}}}}
    assert dynamic_sampling.adjusted_values(sampling, "creative") == {"temperature": 2.0, "top_p": 1.0}


def _agent(recent, text):
    data = {dynamic_sampling.RECENT_TOOLS_KEY: recent}
    return types.SimpleNamespace(
        get_data=data.get, set_data=data.__setitem__, data=data,
        loop_data=types.SimpleNamespace(user_message=types.SimpleNamespace(content=text)),
    )


def _call(agent):
    from plugins._model_config.extensions.python.chat_model_call_before import _20_dynamic_sampling as ext

    model = types.SimpleNamespace(kwargs={}, a0_model_conf=types.SimpleNamespace(provider="llama_cpp"))
    asyncio.run(ext.DynamicSampling(agent=agent).execute(call_data={"model": model}))
    return model.kwargs


def test_dynamic_sampling_is_off_by_default(monkeypatch):
    monkeypatch.setattr(model_config, "get_sampling", lambda agent=None: {"dynamic": False, "dynamic_rules": RULES})
    assert _call(_agent(["text_editor"], "fix it")) == {}


def test_dynamic_sampling_adjusts_this_call_when_on(monkeypatch):
    monkeypatch.setattr(model_config, "get_sampling", lambda agent=None: {"dynamic": True, "dynamic_rules": RULES})
    agent = _agent(["text_editor"], "fix it")
    kwargs = _call(agent)
    assert kwargs["temperature"] == 0.3 and kwargs["top_p"] == 0.93
    assert kwargs["extra_body"] == {"repeat_penalty": 1.1}
    assert agent.data["_dynamic_sampling_last"]["mode"] == "code"


def test_the_shipped_defaults_keep_dynamic_off():
    from helpers import plugins

    defaults = plugins.get_default_plugin_config("_model_config")
    assert defaults["sampling"]["dynamic"] is False
    assert defaults["single_model_mode"] is False

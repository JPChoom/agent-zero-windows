from plugins._model_config.helpers.model_config import utility_kwargs


def test_lm_studio_utility_calls_turn_reasoning_off():
    out = utility_kwargs("lm_studio", {"temperature": 0.2})
    assert out["a0_api_mode"] == "chat_completions"
    assert out["extra_body"] == {"reasoning_effort": "none"}
    assert out["temperature"] == 0.2


def test_user_kwargs_win():
    out = utility_kwargs("lm_studio", {"extra_body": {"reasoning_effort": "low"}, "a0_api_mode": "responses"})
    assert out["extra_body"]["reasoning_effort"] == "low"
    assert out["a0_api_mode"] == "responses"


def test_other_providers_are_untouched():
    assert utility_kwargs("openai", {"a": 1}) == {"a": 1}

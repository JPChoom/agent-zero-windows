"""Tests for the history compression budget.

The budget decides when compression runs at all. Getting it wrong is not
visible as a bug - history simply reports itself "under limit" while the
real prompt is already too large for the window, and the failure surfaces
much later as a provider-side context overflow.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from helpers import history as history_mod
from helpers.history import History


CTX = 65536


@pytest.fixture
def hist(monkeypatch):
    monkeypatch.setattr(
        history_mod,
        "get_chat_model_config",
        lambda agent=None: {"ctx_length": CTX, "ctx_history": 0.7},
    )
    return History(agent=object())


def test_without_a_measurement_the_ratio_is_used(hist):
    """First turn of a chat: nothing has been measured yet, so behaviour
    must be exactly what it was before."""
    assert hist.measured_overhead == 0
    assert hist._get_ctx_size_for_history() == int(CTX * 0.7)


def test_a_large_system_prompt_shrinks_the_budget(hist):
    """The case that motivated this: at 65k the 0.7 ratio leaves 19.6k for
    everything that is not history, and A0's system prompt plus extras can
    exceed that. The budget must come down, not stay at 45.8k."""
    hist.set_measured_overhead(25000)
    budget = hist._get_ctx_size_for_history()
    assert budget < int(CTX * 0.7)
    # history + overhead + the reply reserve must still fit the window
    assert budget + 25000 + int(CTX * history_mod.OUTPUT_RESERVE_RATIO) <= CTX


def test_a_small_overhead_does_not_raise_the_budget(hist):
    """ctx_history stays a ceiling: a cheap prompt must not let history
    expand past what the user configured."""
    hist.set_measured_overhead(1000)
    assert hist._get_ctx_size_for_history() == int(CTX * 0.7)


def test_the_budget_is_floored(hist):
    """An overhead near the whole window would drive the budget to zero or
    below, and compression would loop forever chasing a target it can
    never reach."""
    hist.set_measured_overhead(CTX * 2)
    assert hist._get_ctx_size_for_history() == int(CTX * history_mod.MIN_HISTORY_RATIO)


def test_negative_overhead_is_ignored(hist):
    """get_tokens() and the prompt estimator disagree slightly; a negative
    difference must not be read as a bonus budget."""
    hist.set_measured_overhead(-5000)
    assert hist.measured_overhead == 0
    assert hist._get_ctx_size_for_history() == int(CTX * 0.7)


def test_is_over_limit_follows_the_measured_budget(hist, monkeypatch):
    monkeypatch.setattr(History, "get_tokens", lambda self: 40000)
    assert hist.is_over_limit() is False  # 40k < 45.8k on the ratio alone
    hist.set_measured_overhead(25000)
    assert hist.is_over_limit() is True  # but 40k + 25k + reserve does not fit

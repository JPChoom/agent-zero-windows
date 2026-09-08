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


def _make_history(monkeypatch, **cfg):
    base = {"ctx_length": CTX, "ctx_history": 0.7}
    base.update(cfg)
    monkeypatch.setattr(
        history_mod, "get_chat_model_config", lambda agent=None: base
    )
    return History(agent=object())


@pytest.fixture
def hist(monkeypatch):
    return _make_history(monkeypatch)


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
    reserve = int(CTX * history_mod.DEFAULT_OUTPUT_RESERVE_RATIO)
    assert budget + 25000 + reserve <= CTX


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


# ------------------------------------------------------------------
# The configurable reply reserve
# ------------------------------------------------------------------

def test_ctx_output_widens_the_reserve(monkeypatch):
    """The point of the setting: a reasoning model that needs room to think
    and still emit a tool call gets it by trading away history, not by
    lowering ctx_history and losing the conversation as well."""
    hist = _make_history(monkeypatch, ctx_output=0.3)
    hist.set_measured_overhead(14300)
    budget = hist._get_ctx_size_for_history()
    assert budget + 14300 + int(CTX * 0.3) <= CTX
    # and it really is tighter than the default reserve would give
    default = _make_history(monkeypatch)
    default.set_measured_overhead(14300)
    assert budget < default._get_ctx_size_for_history()


def test_an_unset_ctx_output_keeps_the_default(hist):
    """Existing configs have no ctx_output; they must not change behaviour."""
    hist.set_measured_overhead(14300)
    expected = CTX - 14300 - int(CTX * history_mod.DEFAULT_OUTPUT_RESERVE_RATIO)
    assert hist._get_ctx_size_for_history() == min(int(CTX * 0.7), expected)


@pytest.mark.parametrize("bad", ["", None, "lots", {}])
def test_an_unparseable_ctx_output_falls_back(monkeypatch, bad):
    hist = _make_history(monkeypatch, ctx_output=bad)
    hist.set_measured_overhead(14300)
    expected = CTX - 14300 - int(CTX * history_mod.DEFAULT_OUTPUT_RESERVE_RATIO)
    assert hist._get_ctx_size_for_history() == min(int(CTX * 0.7), expected)


@pytest.mark.parametrize("ratio,clamped", [(-0.5, 0.0), (2.0, 0.9)])
def test_out_of_range_ctx_output_is_clamped(monkeypatch, ratio, clamped):
    """The slider cannot produce these, but config files are hand-edited. A
    reserve of 1.0 would leave no window at all."""
    hist = _make_history(monkeypatch, ctx_output=ratio)
    assert History._get_ctx_output({"ctx_output": ratio}) == clamped
    hist.set_measured_overhead(1000)
    assert hist._get_ctx_size_for_history() > 0


def test_the_shipped_default_matches_the_yaml():
    """get_plugin_config returns only explicitly-set values, so the code
    fallback is what an existing install actually uses. If it drifts from
    default_config.yaml, new and existing installs behave differently."""
    import re

    yaml_text = (PROJECT_ROOT / "plugins/_model_config/default_config.yaml").read_text(
        encoding="utf-8"
    )
    found = re.search(r"^  ctx_output:\s*([0-9.]+)", yaml_text, re.MULTILINE)
    assert found, "ctx_output missing from default_config.yaml"
    assert float(found.group(1)) == history_mod.DEFAULT_OUTPUT_RESERVE_RATIO


# ------------------------------------------------------------------
# The measurement itself
# ------------------------------------------------------------------

def test_overhead_is_measured_against_the_prompt_snapshot(monkeypatch):
    """Regression: history compression runs on a background thread and can
    shrink history *while* prepare_prompt is assembling the prompt. If the
    overhead is computed by re-reading history rather than from the same
    snapshot the prompt was built from, it absorbs whatever compression
    just removed. That inflated overhead shrinks the next budget, which
    triggers more compression - a runaway that hammers the utility model
    and collapses history to the floor.
    """
    import agent as agent_mod
    import inspect

    source = inspect.getsource(agent_mod.Agent.prepare_prompt)
    assert "set_measured_overhead" in source
    measurement = source.split("set_measured_overhead", 1)[1]
    # The subtracted term must come from the snapshot, not from history.
    assert "self.history.get_tokens()" not in measurement, (
        "overhead must not be measured by re-reading history - see the "
        "runaway described above"
    )


def test_a_snapshot_measurement_is_stable_under_concurrent_compression(hist):
    """The arithmetic the fix relies on: overhead derived from one snapshot
    does not move when history changes underneath it."""
    snapshot_prompt_tokens = 60000
    snapshot_history_tokens = 46000

    overhead = snapshot_prompt_tokens - snapshot_history_tokens
    hist.set_measured_overhead(overhead)
    stable = hist._get_ctx_size_for_history()

    # Had it re-read history mid-compression it would have seen, say, 20k,
    # producing a far larger overhead and a collapsed budget.
    hist.set_measured_overhead(snapshot_prompt_tokens - 20000)
    collapsed = hist._get_ctx_size_for_history()

    # Roughly halved, and far below what ctx_history alone would allow -
    # each such turn would compress history hard and re-inflate next turn.
    assert collapsed < stable / 2
    assert collapsed < int(CTX * 0.7) / 2


# ------------------------------------------------------------------
# Overhead peak-hold
# ------------------------------------------------------------------

def test_overhead_rises_immediately(hist):
    """A turn whose extras grow must tighten the budget on that turn, not
    the one after."""
    hist.set_measured_overhead(10000)
    hist.set_measured_overhead(20000)
    assert hist.measured_overhead == 20000


def test_overhead_falls_only_slowly(hist):
    """Regression: the budget is set from the previous turn's overhead but
    the prompt is assembled from this turn's. Extras move between turns -
    skills, recalled memories, tool results - so taking the last reading
    literally left history compressed against a budget that was already
    too generous, and the prompt guard had to drop messages. Observed
    live twice: 5 of 121 messages withheld, then 1 of 74."""
    hist.set_measured_overhead(20000)
    hist.set_measured_overhead(10000)
    assert hist.measured_overhead > 10000, "a dip must not discard the peak"
    assert hist.measured_overhead < 20000, "but it must decay, not stick"


def test_a_sustained_drop_is_eventually_forgotten(hist):
    """Overestimating costs history headroom, so the peak must not be
    permanent - a genuinely smaller prompt should reclaim its room."""
    hist.set_measured_overhead(20000)
    for _ in range(200):
        hist.set_measured_overhead(5000)
    assert hist.measured_overhead == 5000


def test_the_peak_tightens_the_budget(hist):
    """The point of holding it: the budget must reflect the spike."""
    hist.set_measured_overhead(25000)
    tight = hist._get_ctx_size_for_history()
    hist.set_measured_overhead(5000)   # a quieter turn right after
    assert hist._get_ctx_size_for_history() < int(CTX * 0.7)
    assert hist._get_ctx_size_for_history() >= tight


def test_negative_still_cannot_raise_the_budget(hist):
    hist.set_measured_overhead(-5000)
    assert hist.measured_overhead == 0

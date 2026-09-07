"""Tests for the utility-model input guard on history summarization.

call_utility_model does no trimming of its own, so nothing bounded a
summarization request except the history budget. That went unnoticed
because the utility model in use was loaded larger than Agent Zero had
been told; configure one at its true smaller size and compression would
fail on the oversized request, exactly when it is most needed.

These also pin ctx_input to a consumer. It was previously read by nothing
at all - a settings slider that controlled no behaviour.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from helpers import history as history_mod
from helpers import tokens

SYSTEM = "You are AI summarization assistant. " * 20


class _Agent:
    """Records what the utility model was actually asked to read."""

    def __init__(self):
        self.sent = None

    def read_prompt(self, name, **kw):
        if name == "fw.topic_summary.sys.md":
            return SYSTEM
        return f"# Message history to summarize:\n{kw.get('content', '')}"

    async def call_utility_model(self, system, message):
        self.sent = message
        return "a summary"


@pytest.fixture
def agent(monkeypatch):
    a = _Agent()

    def configure(ctx_length=65536, **extra):
        cfg = {"ctx_length": ctx_length, **extra}
        monkeypatch.setattr(
            history_mod, "get_utility_model_config", lambda agent=None: cfg
        )

    a.configure = configure
    configure()
    return a


def _big(n_tokens):
    # each "word " is roughly one token
    return " ".join(f"w{i}" for i in range(n_tokens))


@pytest.mark.asyncio
async def test_content_within_budget_is_sent_whole(agent):
    content = _big(200)
    await history_mod.summarize_content(agent, content)
    assert content in agent.sent
    assert "omitted" not in agent.sent


@pytest.mark.asyncio
async def test_oversized_content_is_trimmed_to_the_budget(agent):
    """The case the guard exists for: a request larger than the utility
    model can read must be cut down rather than sent and rejected."""
    agent.configure(ctx_length=4000, ctx_input=0.7)
    await history_mod.summarize_content(agent, _big(20000))
    assert tokens.approximate_tokens(agent.sent) <= 4000


@pytest.mark.asyncio
async def test_trimming_keeps_both_ends_and_says_what_it_dropped(agent):
    """A summary needs the request that opened the topic and the outcome
    that closed it; the working detail between them is what to lose."""
    agent.configure(ctx_length=4000, ctx_input=0.7)
    content = "FIRST_MARKER " + _big(20000) + " LAST_MARKER"
    await history_mod.summarize_content(agent, content)
    assert "FIRST_MARKER" in agent.sent
    assert "LAST_MARKER" in agent.sent
    assert "omitted" in agent.sent


@pytest.mark.asyncio
async def test_ctx_input_actually_changes_what_is_sent(agent):
    """ctx_input previously reached no code path at all. If this passes and
    the ratio is ignored again, the setting is dead once more."""
    content = _big(30000)

    agent.configure(ctx_length=32768, ctx_input=0.7)
    await history_mod.summarize_content(agent, content)
    generous = tokens.approximate_tokens(agent.sent)

    agent.configure(ctx_length=32768, ctx_input=0.2)
    await history_mod.summarize_content(agent, content)
    stingy = tokens.approximate_tokens(agent.sent)

    assert stingy < generous


@pytest.mark.asyncio
async def test_ctx_length_actually_changes_what_is_sent(agent):
    content = _big(30000)

    agent.configure(ctx_length=32768, ctx_input=0.7)
    await history_mod.summarize_content(agent, content)
    big = tokens.approximate_tokens(agent.sent)

    agent.configure(ctx_length=8192, ctx_input=0.7)
    await history_mod.summarize_content(agent, content)
    small = tokens.approximate_tokens(agent.sent)

    assert small < big


def test_an_unset_ctx_input_uses_the_documented_default(agent):
    agent.configure(ctx_length=10000)
    expected = int(10000 * history_mod.DEFAULT_UTILITY_CTX_INPUT)
    assert history_mod._get_utility_input_budget(agent) == expected


@pytest.mark.parametrize("bad", ["", None, "most of it", {}])
def test_an_unparseable_ctx_input_falls_back(agent, bad):
    agent.configure(ctx_length=10000, ctx_input=bad)
    expected = int(10000 * history_mod.DEFAULT_UTILITY_CTX_INPUT)
    assert history_mod._get_utility_input_budget(agent) == expected


@pytest.mark.parametrize("ratio", [-1.0, 0.0, 5.0])
def test_out_of_range_ctx_input_still_leaves_a_usable_budget(agent, ratio):
    """A hand-edited 0 or negative would otherwise send an empty prompt,
    and compression would silently summarize nothing."""
    agent.configure(ctx_length=10000, ctx_input=ratio)
    budget = history_mod._get_utility_input_budget(agent)
    assert budget >= history_mod.MIN_SUMMARY_INPUT_TOKENS
    assert budget <= 10000


@pytest.mark.asyncio
async def test_a_tiny_model_still_gets_a_readable_request(agent):
    """Prompt overhead can exceed a very small budget outright. Sending an
    empty conversation would make compression a no-op that still costs a
    model call."""
    agent.configure(ctx_length=100, ctx_input=0.1)
    await history_mod.summarize_content(agent, _big(5000))
    body = agent.sent.split("summarize:\n", 1)[1]
    assert body.strip()

"""Tests for the prompt-size safety net in prepare_prompt.

Compression is what normally keeps history inside its budget, but nothing
guaranteed it succeeded. When it could not reduce far enough, the
oversized prompt reached the provider and came back as a hard error
("Context size has been exceeded"), losing the turn. Reproduced live: a
history stuck 3k above budget produced a 53,090-token prompt in a 65,536
window.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import agent as agent_mod
from helpers import history, tokens

CTX = 65536


class _Log:
    def __init__(self):
        self.items = []

    def log(self, **kw):
        self.items.append(kw)
        return type("Item", (), {"update": lambda **k: None})()


class _Context:
    def __init__(self):
        self.log = _Log()


def _agent(monkeypatch, ctx_output=0.25):
    monkeypatch.setattr(
        history,
        "get_chat_model_config",
        lambda agent=None: {
            "ctx_length": CTX,
            "ctx_history": 0.7,
            "ctx_output": ctx_output,
        },
    )
    a = agent_mod.Agent.__new__(agent_mod.Agent)
    a.context = _Context()  # type: ignore[attr-defined]
    return a


def _msg(text):
    return {"ai": False, "content": text}


def _words(n):
    return " ".join(f"w{i}" for i in range(n))


def _prompt_tokens(system_text, out):
    return tokens.approximate_prompt_tokens(
        system_text + history.output_text(out)
    )


def test_a_prompt_that_fits_is_left_alone(monkeypatch):
    a = _agent(monkeypatch)
    out = [_msg(_words(100)) for _ in range(5)]
    assert a._fit_history_to_window("system", [], [], out) is out
    assert a.context.log.items == []


def test_an_oversized_prompt_is_brought_under_the_limit(monkeypatch):
    a = _agent(monkeypatch)
    out = [_msg(_words(6000)) for _ in range(12)]  # far over the window
    kept = a._fit_history_to_window("system", [], [], out)
    limit = CTX - int(CTX * 0.25)
    assert _prompt_tokens("system", kept) <= limit


def test_the_newest_messages_are_the_ones_kept(monkeypatch):
    """Dropping the recent turn would discard the thing being answered."""
    a = _agent(monkeypatch)
    out = [_msg("OLDEST " + _words(6000))] + [
        _msg(_words(6000)) for _ in range(10)
    ] + [_msg("NEWEST " + _words(10))]
    kept = a._fit_history_to_window("system", [], [], out)
    rendered = history.output_text(kept)
    assert "NEWEST" in rendered
    assert "OLDEST" not in rendered


def test_one_message_always_survives(monkeypatch):
    """A prompt with no conversation at all cannot be answered."""
    a = _agent(monkeypatch)
    out = [_msg(_words(60000)) for _ in range(3)]
    kept = a._fit_history_to_window("system", [], [], out)
    assert len(kept) >= 1


def test_the_model_is_told_the_prompt_was_trimmed(monkeypatch):
    """Silently dropping context would leave the agent confidently acting
    on a conversation it cannot see."""
    a = _agent(monkeypatch)
    out = [_msg(_words(6000)) for _ in range(12)]
    kept = a._fit_history_to_window("system", [], [], out)
    assert "omitted from this request" in history.output_text(kept)


def test_the_user_is_warned(monkeypatch):
    a = _agent(monkeypatch)
    out = [_msg(_words(6000)) for _ in range(12)]
    a._fit_history_to_window("system", [], [], out)
    warnings = [i for i in a.context.log.items if i.get("type") == "warning"]
    assert warnings and "context window" in warnings[0]["heading"].lower()


def test_a_system_prompt_that_alone_overflows_drops_nothing(monkeypatch):
    """Dropping history cannot help here, and would discard the whole
    conversation for no gain."""
    a = _agent(monkeypatch)
    out = [_msg(_words(50)) for _ in range(3)]
    kept = a._fit_history_to_window(_words(200000), [], [], out)
    assert kept is out
    assert a.context.log.items == []


def test_protocol_and_extras_count_against_the_budget(monkeypatch):
    """They ride in the same request as history; ignoring them would let
    the assembled prompt overflow anyway."""
    a = _agent(monkeypatch)
    out = [_msg(_words(3000)) for _ in range(12)]
    without = a._fit_history_to_window("system", [], [], list(out))
    with_extras = a._fit_history_to_window(
        "system", [_msg(_words(2000))], [_msg(_words(1000))], list(out)
    )
    assert len(with_extras) < len(without)


def test_a_bigger_reserve_trims_more(monkeypatch):
    """The guard must honour ctx_output, or it would hand the model a
    prompt that fits the window with no room left to answer."""
    a_small = _agent(monkeypatch, ctx_output=0.05)
    out = [_msg(_words(3000)) for _ in range(12)]
    small = a_small._fit_history_to_window("system", [], [], list(out))
    a_big = _agent(monkeypatch, ctx_output=0.45)
    big = a_big._fit_history_to_window("system", [], [], list(out))
    assert len(big) < len(small)


def test_an_unresolvable_config_skips_the_guard(monkeypatch):
    """This runs while every prompt is assembled. A config that cannot be
    read must cost at most the safety net, never the turn."""
    def boom(agent=None):
        raise AttributeError("'Agent' object has no attribute 'config'")

    monkeypatch.setattr(history, "get_chat_model_config", boom)
    a = agent_mod.Agent.__new__(agent_mod.Agent)
    a.context = _Context()  # type: ignore[attr-defined]
    out = [_msg(_words(6000)) for _ in range(12)]
    assert a._fit_history_to_window("system", [], [], out) is out

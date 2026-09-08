"""Tests for routing a <clarify> verdict to a human instead of the agent.

The bug this replaces was observed live: safety_policy denied an
Invoke-WebRequest, the agent moved the same request into a node script,
the infection check caught the workaround and asked "Are you okay with
the agent using node fetch...?" - and the main model answered it, in the
user's voice ("Go ahead and run it"), clearing its own gate.

So every test here is really the same question: can this gate open
without a human saying yes?
"""

import asyncio

import pytest

from plugins._infection_check.helpers import checker as C
from plugins._safety_policy.helpers import approval_registry


class _LogItem:
    def __init__(self):
        self.kvps = {}
        self.updates = []

    def update(self, **kw):
        self.updates.append(kw)
        self.kvps.update(kw)


class _Log:
    def __init__(self):
        # Named `logs` to match helpers/log.py - _retire_stale_requests walks
        # context.log.logs, and a fake with a different attribute name would
        # make that pass vacuously.
        self.logs = []

    @property
    def items(self):
        return self.logs

    def log(self, **kw):
        item = _LogItem()
        item.kvps.update(kw.get("kvps", {}))
        item.type = kw.get("type")
        item.content = kw.get("content")
        self.logs.append(item)
        return item

    def set_progress(self, *a, **k):
        pass


class _Context:
    id = "ctx"

    def __init__(self):
        self.log = _Log()


class _Agent:
    agent_name = "A0"

    def __init__(self):
        self.context = _Context()


def _checker(**cfg):
    base = {"prompt": "p", "clarification_timeout_seconds": 0.4}
    base.update(cfg)
    ch = C.InfectionChecker(config=base, iteration=0)
    ch._tool_name = "code_execution_tool"
    ch._tool_args = {"code": "node probe-api.js"}
    return ch


def _pending_id(agent):
    """The approval_id of the request actually awaiting an answer.

    Newest-first and unresolved-only. A chat can hold retired prompts from
    earlier attempts, and answering one of those resolves nothing - so a
    first-match lookup would let a test pass while the real prompt quietly
    timed out.
    """
    for item in reversed(agent.context.log.logs):
        if getattr(item, "type", "") != "infection_check_clarification_request":
            continue
        if item.kvps.get("resolved"):
            continue
        return item.kvps.get("approval_id")
    return None


async def _answer(agent, approved, delay=0.05):
    """Act as the person clicking Allow or Block."""
    for _ in range(200):
        approval_id = _pending_id(agent)
        if approval_id:
            await asyncio.sleep(delay)
            return approval_registry.resolve(approval_id, approved)
        await asyncio.sleep(0.005)
    raise AssertionError("no clarification request was ever published")


@pytest.mark.asyncio
async def test_user_mode_is_the_default():
    """An install that never sets clarify_mode must get the human prompt,
    not the self-answering loop."""
    assert _checker().clarify_mode == "user"


@pytest.mark.asyncio
async def test_allow_lets_the_call_proceed():
    agent = _Agent()
    ch = _checker()
    item = _LogItem()
    task = asyncio.ensure_future(ch._clarify_loop(agent, "Are you okay with this?", item))
    assert await _answer(agent, True)
    action, _detail, cot = await task
    assert action == "ok"
    assert "allowed by the user" in cot


@pytest.mark.asyncio
async def test_block_terminates():
    agent = _Agent()
    ch = _checker()
    item = _LogItem()
    task = asyncio.ensure_future(ch._clarify_loop(agent, "Are you okay with this?", item))
    assert await _answer(agent, False)
    action, detail, _cot = await task
    assert action == "terminate"
    assert "blocked" in detail.lower()


@pytest.mark.asyncio
async def test_no_answer_blocks_rather_than_passes():
    """Fails closed. Proceeding because nobody was watching is exactly what
    this control exists to prevent."""
    agent = _Agent()
    ch = _checker(clarification_timeout_seconds=0.05)
    action, detail, _cot = await ch._clarify_loop(agent, "question?", _LogItem())
    assert action == "terminate"
    assert "treated as blocked" in detail.lower()


@pytest.mark.asyncio
async def test_a_registry_failure_blocks_rather_than_passes(monkeypatch):
    """An error on the approval path must not become an open gate."""
    def boom(approval_id):
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(C.approval_registry, "register", boom)
    action, _detail, _cot = await _checker()._clarify_loop(
        _Agent(), "question?", _LogItem()
    )
    assert action == "terminate"


@pytest.mark.asyncio
async def test_the_main_model_is_never_consulted(monkeypatch):
    """The whole point: the model being gated must not be the one that
    answers the gate."""
    agent = _Agent()

    def fail(*a, **k):
        raise AssertionError("the agent was asked to answer its own gate")

    agent.get_chat_model = fail  # type: ignore[attr-defined]
    ch = _checker()
    task = asyncio.ensure_future(ch._clarify_loop(agent, "question?", _LogItem()))
    await _answer(agent, True)
    action, _d, _c = await task
    assert action == "ok"


@pytest.mark.asyncio
async def test_the_prompt_carries_what_is_being_gated():
    """A question without the call it refers to cannot be decided on."""
    agent = _Agent()
    ch = _checker()
    task = asyncio.ensure_future(ch._clarify_loop(agent, "Allow node fetch?", _LogItem()))

    # Inspect the request as published, before any decision: this is the
    # state the buttons render from.
    for _ in range(200):
        if _pending_id(agent):
            break
        await asyncio.sleep(0.005)
    item = next(
        i for i in agent.context.log.items
        if getattr(i, "type", "") == "infection_check_clarification_request"
    )
    assert item.kvps["question"] == "Allow node fetch?"
    assert item.kvps["tool_name"] == "code_execution_tool"
    assert "probe-api.js" in item.kvps["tool_args"]
    assert item.kvps["resolved"] is False, "must render as actionable, not pre-resolved"

    approval_registry.resolve(item.kvps["approval_id"], True)
    await task


@pytest.mark.asyncio
async def test_the_request_is_marked_resolved_after_a_decision():
    """A prompt left looking actionable after it was answered invites a
    second click that silently does nothing."""
    agent = _Agent()
    ch = _checker()
    task = asyncio.ensure_future(ch._clarify_loop(agent, "q?", _LogItem()))
    await _answer(agent, True)
    await task

    item = next(
        i for i in agent.context.log.items
        if getattr(i, "type", "") == "infection_check_clarification_request"
    )
    assert item.kvps.get("resolved") is True
    assert item.kvps.get("outcome") == "allowed"


@pytest.mark.asyncio
async def test_agent_mode_still_available_for_headless_runs(monkeypatch):
    """Kept deliberately: with nobody to answer, a prompt only ever times
    out and blocks. It must be opt-in, never the default."""
    called = {}

    async def fake(self, agent, text, item):
        called["yes"] = True
        return "ok", "", ""

    monkeypatch.setattr(C.InfectionChecker, "_clarify_with_agent", fake)
    ch = _checker(clarify_mode="agent")
    await ch._clarify_loop(_Agent(), "q?", _LogItem())
    assert called.get("yes")


def test_the_shipped_default_is_user_mode():
    """get_plugin_config returns only explicitly-set values, so the code
    fallback is what most installs use; it must match the YAML."""
    from pathlib import Path

    from helpers import yaml as yaml_helper

    path = Path("plugins/_infection_check/default_config.yaml")
    data = yaml_helper.loads(path.read_text(encoding="utf-8")) or {}
    assert data.get("clarify_mode") == "user"
    assert _checker().clarify_mode == "user"


# ------------------------------------------------------------------
# Stale prompts
# ------------------------------------------------------------------

class _LoggedItem(_LogItem):
    def __init__(self, type_, kvps):
        super().__init__()
        self.type = type_
        self.kvps = dict(kvps)


@pytest.mark.asyncio
async def test_an_earlier_open_prompt_is_retired():
    """After a timeout the agent re-asks on its next attempt, and every ask
    used to publish a fresh request. Observed live: the same question
    asked three times, one left sitting unresolved with Allow/Block still
    rendered. Its future is gone, so those buttons resolve nothing."""
    agent = _Agent()
    stale = _LoggedItem("infection_check_clarification_request",
                        {"approval_id": "old-id", "resolved": False})
    agent.context.log.logs.append(stale)

    ch = _checker()
    task = asyncio.ensure_future(ch._clarify_loop(agent, "same question?", _LogItem()))
    await _answer(agent, True)
    await task

    assert stale.kvps.get("resolved") is True
    assert stale.kvps.get("outcome") == "superseded"


@pytest.mark.asyncio
async def test_an_already_resolved_prompt_is_left_alone():
    """A prompt someone actually answered keeps its real outcome."""
    agent = _Agent()
    done = _LoggedItem("infection_check_clarification_request",
                       {"approval_id": "done-id", "resolved": True,
                        "outcome": "allowed"})
    agent.context.log.logs.append(done)

    ch = _checker()
    task = asyncio.ensure_future(ch._clarify_loop(agent, "q?", _LogItem()))
    await _answer(agent, True)
    await task

    assert done.kvps.get("outcome") == "allowed"


def test_the_timeout_default_matches_the_yaml():
    """get_plugin_config returns only explicitly-set values, so the code
    fallback is what most installs actually use."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    yaml_text = (root / "plugins/_infection_check/default_config.yaml").read_text(
        encoding="utf-8"
    )
    found = re.search(r"^clarification_timeout_seconds:\s*(\d+)", yaml_text, re.M)
    assert found
    # A config with the key absent is what an existing install produces.
    ch = C.InfectionChecker(config={"prompt": "p"}, iteration=0)
    assert ch.clarification_timeout_seconds == float(found.group(1))

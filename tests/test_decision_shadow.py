"""The decision model only watches: it predicts and logs, and changes nothing."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins._model_config.helpers import decision_shadow, job_routing, model_config

ROOT = Path(__file__).resolve().parents[1]
ANSWER = {"model": "laya", "answers": {"next_step": {"type": "choice", "choice": "routine",
                                                     "probabilities": {"routine": 0.8, "deep": 0.2}, "confidence": 0.6}}}


class _Message:
    def __init__(self, text):
        self.text = text

    def output_text(self):
        return self.text


def _agent(result="tool finished", request="private request text"):
    return SimpleNamespace(
        number=0,
        context=SimpleNamespace(id="chat1"),
        config=SimpleNamespace(profile="developer"),
        loop_data=SimpleNamespace(iteration=2, user_message=_Message(request)),
        history=SimpleNamespace(current=SimpleNamespace(messages=[_Message(result)])),
    )


@pytest.fixture
def shadow(monkeypatch, tmp_path):
    log = tmp_path / "decisions.jsonl"
    posts = []

    def post(url, body):
        posts.append((url, json.loads(body)))
        return ANSWER

    monkeypatch.setattr(decision_shadow, "_post", post)
    monkeypatch.setattr(decision_shadow.files, "get_abs_path", lambda *a, **k: str(log))
    monkeypatch.setattr(decision_shadow, "_pending", {})
    routing = {"decision_shadow": {"enabled": True, "model": "laya", "api_base": ""}}
    monkeypatch.setattr(job_routing, "settings", lambda agent=None: routing)
    monkeypatch.setattr(model_config, "get_utility_model_config", lambda agent=None: {"api_base": "http://203.0.113.5:1234/v1"})
    monkeypatch.setattr(model_config, "get_config", lambda agent=None, **k: {})
    return SimpleNamespace(log=log, posts=posts, routing=routing)


async def _drain():
    while decision_shadow._tasks:
        await asyncio.gather(*list(decision_shadow._tasks))


def _rows(shadow):
    return [json.loads(line) for line in shadow.log.read_text(encoding="utf-8").splitlines()]


def test_a_step_is_logged_with_what_really_happened(shadow):
    async def run():
        agent = _agent()
        decision_shadow.start_thinking(agent)
        decision_shadow.finish_thinking(agent, "the answer", "thought about it")
        await _drain()

    asyncio.run(run())
    url, body = shadow.posts[0]
    assert url == "http://203.0.113.5:1234/v1/systemone" and body["model"] == "laya"
    assert set(body["questions"]["next_step"]["criteria"]) == {"routine", "deep"}
    row = _rows(shadow)[0]
    assert (row["choice"], row["confidence"], row["reasoning_chars"], row["response_chars"]) == ("routine", 0.6, 16, 10)
    assert row["step"] == 2 and row["trouble_before"] is False


def test_the_log_never_holds_the_text(shadow):
    async def run():
        agent = _agent()
        decision_shadow.start_thinking(agent)
        decision_shadow.finish_thinking(agent, "secret reply", "secret reasoning")
        await _drain()

    asyncio.run(run())
    text = shadow.log.read_text(encoding="utf-8")
    assert "private" not in text and "secret" not in text and len(_rows(shadow)[0]["input_sha256"]) == 64


def test_trouble_and_the_auto_rule_are_recorded(shadow):
    async def run():
        agent = _agent(result="Traceback: command failed")
        decision_shadow.start_thinking(agent)
        decision_shadow.finish_thinking(agent, "", "")
        await _drain()

    asyncio.run(run())
    row = _rows(shadow)[0]
    assert row["trouble_before"] is True and row["rule_thinks"] is True


def test_a_subordinate_is_logged_with_how_long_it_took(shadow):
    async def run():
        agent = _agent()
        decision_shadow.start_subordinate(agent, {"message": "search for x", "profile": "researcher"})
        decision_shadow.finish_subordinate(agent, SimpleNamespace(message="done"))
        await _drain()

    asyncio.run(run())
    row = _rows(shadow)[0]
    assert row["decision"] == "subordinate" and row["subordinate_profile"] == "researcher"
    assert "seconds" in row and row["response_chars"] == 4


def test_a_dead_server_is_logged_and_nothing_is_raised(shadow, monkeypatch):
    def down(url, body):
        raise ConnectionError("gone")

    monkeypatch.setattr(decision_shadow, "_post", down)

    async def run():
        agent = _agent()
        decision_shadow.start_thinking(agent)
        decision_shadow.finish_thinking(agent, "reply", "")
        await _drain()

    asyncio.run(run())
    assert _rows(shadow)[0]["error"] == "ConnectionError"


def test_a_step_does_not_wait_for_the_decision(shadow, monkeypatch):
    release = None

    async def slow(agent, state, questions):
        await release.wait()
        return {"choice": "routine", "ms": 1}

    monkeypatch.setattr(decision_shadow, "ask", slow)

    async def run():
        nonlocal release
        release = asyncio.Event()
        agent = _agent()
        decision_shadow.start_thinking(agent)  # returns at once
        decision_shadow.finish_thinking(agent, "reply", "")
        assert not shadow.log.exists()
        release.set()
        await _drain()

    asyncio.run(run())
    assert len(_rows(shadow)) == 1


def test_an_outcome_with_no_prediction_is_ignored(shadow):
    decision_shadow.finish_thinking(_agent(), "reply", "")
    assert not shadow.log.exists()


def test_it_is_off_by_default(shadow):
    defaults = (ROOT / "plugins/_model_config/default_config.yaml").read_text(encoding="utf-8")
    assert "decision_shadow:\n    enabled: false" in defaults.replace("\r\n", "\n")
    shadow.routing["decision_shadow"]["enabled"] = False
    module = importlib.import_module(
        "plugins._model_config.extensions.python.chat_model_call_before._05_decision_shadow")
    data = {"model": "m", "background": False}

    async def run():
        await module.DecisionShadow(agent=_agent()).execute(call_data=data)

    asyncio.run(run())
    assert not shadow.posts and data == {"model": "m", "background": False}


def test_background_calls_are_not_steps(shadow):
    module = importlib.import_module(
        "plugins._model_config.extensions.python.chat_model_call_before._05_decision_shadow")

    async def run():
        await module.DecisionShadow(agent=_agent()).execute(call_data={"model": "m", "background": True})
        await _drain()

    asyncio.run(run())
    assert not shadow.posts


def test_a_prediction_cannot_touch_the_call(shadow):
    module = importlib.import_module(
        "plugins._model_config.extensions.python.chat_model_call_before._05_decision_shadow")
    model = SimpleNamespace(kwargs={"temperature": 0.2})
    data = {"model": model, "background": False, "messages": []}

    async def run():
        await module.DecisionShadow(agent=_agent()).execute(call_data=data)
        await _drain()

    asyncio.run(run())
    assert data["model"] is model and model.kwargs == {"temperature": 0.2}


def _report():
    spec = importlib.util.spec_from_file_location("report", ROOT / "tests/manual/decision_shadow_report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(step, choice, trouble=False, **extra):
    return {"decision": "thinking", "context_id": "c", "agent": 0, "step": step, "choice": choice,
            "trouble_before": trouble, "reasoning_chars": 100, "seconds": 5, "ms": 20, "confidence": 0.6, **extra}


def test_the_report_links_a_step_to_the_trouble_after_it():
    summary = _report().summarize([_row(1, "routine"), _row(2, "deep", trouble=True), _row(3, "routine")])
    assert summary["thinking"]["predicted routine"]["steps"] == 2
    assert summary["thinking"]["predicted routine"]["trouble_after_%"] == 100.0
    assert summary["thinking"]["predicted deep"]["trouble_after_%"] == 0.0


def test_the_report_does_not_link_across_runs():
    rows = [_row(1, "routine"), {**_row(2, "deep", trouble=True), "context_id": "other"}]
    assert _report().summarize(rows)["thinking"]["predicted routine"]["trouble_after_%"] is None


def test_the_report_counts_failures_and_subordinates():
    rows = [{"decision": "thinking", "error": "Timeout", "ms": 5000},
            {"decision": "subordinate", "choice": "simple", "seconds": 10, "ms": 30},
            {"decision": "subordinate", "choice": "hard", "seconds": 90, "ms": 30}]
    summary = _report().summarize(rows)
    assert summary["failed_requests"] == 1 and summary["median_decide_ms"] == 30
    assert summary["subordinate"]["hard"]["median_seconds"] == 90

"""The sidebar speed counter: what perf.live_state() reports."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from helpers import perf

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    monkeypatch.setattr(perf, "_live_calls", {})
    monkeypatch.setattr(perf, "_last_live", None)
    monkeypatch.setattr(perf, "perf_dir", lambda: str(tmp_path))


def _call(role="main", background=False, caller="", streamed=True, model="hosted_vllm/Big-Model"):
    call = perf.ModelCall(model=model, role=role, context_id="chat", prompt_chars=4000, caller=caller, background=background)
    call.streamed = streamed
    call.slot_acquired()
    return call


def test_idle_with_nothing_running():
    assert perf.live_state() == {"phase": "idle", "tok_s": None, "last": None}


def test_an_answer_with_no_tokens_yet_is_reading_the_prompt():
    _call()
    state = perf.live_state()
    assert state["phase"] == "reading" and state["tok_s"] is None
    assert state["model"] == "Big-Model" and state["prompt_tokens"] == 1000


def test_writing_and_thinking_are_told_apart():
    call = _call()
    call.chunk("hmm", "")
    assert perf.live_state()["phase"] == "thinking"
    call.chunk("", "answer")
    assert perf.live_state()["phase"] == "writing"


def test_the_rate_covers_recent_seconds():
    call = _call()
    now = time.monotonic()
    call.first_chunk_at = now - 2
    call.samples = [(now - 2.0, 0), (now - 1.0, 400), (now, 800)]
    assert perf.live_state()["tok_s"] == pytest.approx(100.0, abs=2)


def test_old_samples_do_not_count():
    call = _call()
    now = time.monotonic()
    call.first_chunk_at = now - 60
    call.samples = [(now - 60, 0), (now - 1.0, 4000), (now, 4400)]
    assert perf.live_state()["tok_s"] == pytest.approx(100.0, abs=2)


def test_a_stalled_stream_reads_zero():
    call = _call()
    now = time.monotonic()
    call.first_chunk_at = now - 30
    call.samples = [(now - 20, 100), (now - 10, 200)]
    assert perf.live_state()["tok_s"] == 0.0


def test_a_finished_answer_stays_as_the_last_value():
    call = _call()
    call.reuse = {"kept": 0.97}
    call.chunk("", "x" * 400)
    call.first_chunk_at = time.monotonic() - 1
    call.finish()
    state = perf.live_state()
    assert state["phase"] == "idle" and state["last"]["model"] == "Big-Model"
    assert state["last"]["tok_s"] == pytest.approx(100, abs=5) and state["last"]["prompt_kept"] == 0.97


def test_a_failed_call_leaves_the_list():
    call = _call()
    call.finish(RuntimeError("no"))
    assert perf.live_state()["phase"] == "idle" and not perf._live_calls


@pytest.mark.parametrize("kwargs", [
    {"role": "utility"},
    {"background": True},
    {"caller": "infection_check"},
    {"streamed": False},
])
def test_only_the_agents_own_answers_show(kwargs):
    _call(**kwargs)
    assert perf.live_state()["phase"] == "idle"


def test_a_subordinate_on_another_model_shows():
    _call(role="subordinate", model="lm_studio/small")
    state = perf.live_state()
    assert state["role"] == "subordinate" and state["model"] == "small"


def test_the_newest_answer_wins():
    _call(model="first")
    time.sleep(0.01)
    _call(model="second")
    assert perf.live_state()["model"] == "second"


def test_samples_stay_small():
    call = _call()
    for i in range(100):
        call.samples.append((time.monotonic() - 100, i))
    call.samples[-1] = (time.monotonic() - 100, 99)
    call.chunk("", "x")
    assert len(call.samples) <= perf.LIVE_MAX_SAMPLES


def test_the_state_holds_no_text():
    call = _call()
    call.chunk("private reasoning", "private answer")
    assert "private" not in str(perf.live_state())


def test_the_counter_sits_above_tasks_and_is_off_by_default():
    tasks = (ROOT / "webui/components/sidebar/tasks/tasks-list.html").read_text(encoding="utf-8")
    assert tasks.index('id="sidebar-tasks-list-start"') < tasks.index("Tasks\n")
    assert (ROOT / "plugins/_perf/extensions/webui/sidebar-tasks-list-start/speed-counter.html").exists()
    store = (ROOT / "plugins/_perf/webui/speed-counter-store.js").read_text(encoding="utf-8")
    assert 'getItem(STORAGE_KEY) === "1"' in store
    prefs = (ROOT / "webui/components/sidebar/bottom/preferences/preferences-panel.html").read_text(encoding="utf-8")
    assert 'id="sidebar-preferences-list-end"' in prefs

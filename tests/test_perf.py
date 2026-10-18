import asyncio
import json
import time

import pytest

from helpers import perf


@pytest.fixture(autouse=True)
def perf_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(perf, "perf_dir", lambda: str(tmp_path))
    perf.set_enabled(True)
    perf._turns.clear()
    yield tmp_path
    perf._turns.clear()


def _lines(folder, name):
    path = folder / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_model_call_record_splits_wait_first_token_and_speed(perf_dir):
    call = perf.start_model_call("lm_studio/qwen", "main", prompt_chars=4000)
    call.started -= 3.0  # waited 3 s for the backend
    call.slot_acquired()
    call.slot_at = call.started + 3.0
    call.first_chunk_at = call.slot_at + 2.0  # 2 s to first token
    call.chunk("", "")
    call.reasoning_chars = 400
    call.response_chars = 400
    call.ended = call.first_chunk_at + 2.0
    record = call.as_dict()
    assert record["queue_wait_s"] == pytest.approx(3.0, abs=0.01)
    assert record["first_token_s"] == pytest.approx(2.0, abs=0.01)
    assert record["prompt_tokens_est"] == 1000
    assert record["reasoning_tokens_est"] == 100
    assert record["tokens_per_s"] == pytest.approx(100.0, abs=1)
    assert record["background"] is True  # no turn was running


def test_turn_collects_calls_hooks_tools_and_writes_jsonl(perf_dir):
    async def run():
        perf.turn_start("chat-1", "A0")
        call = perf.start_model_call("m", "main", 40)
        call.slot_acquired()
        call.chunk("think", "answer")
        call.finish()
        perf.add_hook_time("chat-1", "system_prompt", "_13_skills_prompt", 0.5)
        perf.add_tool_time("chat-1", "code_execution_tool", 1.25)
        return perf.turn_end("chat-1")

    record = asyncio.run(run())
    assert record["models"]["main"]["calls"] == 1
    assert record["hooks"]["system_prompt"] == 0.5
    assert record["tools_s"] == 1.25
    assert record["slowest_extensions"][0]["extension"] == "_13_skills_prompt"
    assert _lines(perf_dir, "turns.jsonl")[0]["context_id"] == "chat-1"
    calls = _lines(perf_dir, "model_calls.jsonl")
    assert calls[0]["context_id"] == "chat-1" and calls[0]["background"] is False
    line = perf.format_turn(record)
    assert "main 1x" in line and "tools 1.2s" in line and "slowest hook _13_skills_prompt" in line


def test_records_contain_no_text(perf_dir):
    async def run():
        perf.turn_start("chat-2")
        call = perf.start_model_call("m", "utility", 10)
        call.slot_acquired()
        call.chunk("SECRET-REASONING", "SECRET-ANSWER")
        call.finish()
        perf.turn_end("chat-2")

    asyncio.run(run())
    for name in ("model_calls.jsonl", "turns.jsonl"):
        assert "SECRET" not in (perf_dir / name).read_text(encoding="utf-8")


def test_event_loop_stall_is_reported(perf_dir):
    async def run():
        perf.turn_start("chat-3")
        await asyncio.sleep(0.15)  # let the probe start
        time.sleep(0.35)  # blocking work on the loop
        await asyncio.sleep(0.25)
        return perf.turn_end("chat-3")

    record = asyncio.run(run())
    assert record["loop_stall_max_s"] >= 0.2
    assert record["loop_stalls_over_100ms"] >= 1
    assert "UI stalled" in perf.format_turn(record)


def test_failed_call_is_recorded_with_error_type(perf_dir):
    call = perf.start_model_call("m", "utility", 0)
    call.finish(TimeoutError("x"))
    record = _lines(perf_dir, "model_calls.jsonl")[0]
    assert record["ok"] is False and record["error"] == "TimeoutError"


def test_log_file_rotates_at_cap(perf_dir, monkeypatch):
    monkeypatch.setattr(perf, "MAX_LOG_BYTES", 200)
    for _ in range(10):
        perf.start_model_call("m", "main", 0).finish()
    assert (perf_dir / "model_calls.jsonl.1").exists()


@pytest.mark.asyncio
async def test_unified_call_is_measured_with_role(perf_dir, monkeypatch):
    import models

    class _FakeTransport:
        def __init__(self, *a, **k):
            pass

        async def acomplete(self):
            await asyncio.sleep(0.01)
            return {"response_delta": "ok", "reasoning_delta": ""}

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(models, "LiteLLMTransport", _FakeTransport)
    monkeypatch.setattr(models, "apply_rate_limiter", _noop)
    monkeypatch.setattr(models, "configure_litellm", lambda: None)

    chat_model = models.LiteLLMChatWrapper(model="fake-model", provider="fake-provider")
    chat_model.a0_perf_role = "utility"
    await chat_model.unified_call(system_message="sys", user_message="hello")

    record = _lines(perf_dir, "model_calls.jsonl")[-1]
    assert record["role"] == "utility"
    assert record["ok"] is True
    assert record["prompt_tokens_est"] == perf.estimate_tokens(len("sys") + len("hello"))
    assert record["attempts"] == 1


@pytest.mark.asyncio
async def test_extension_hook_time_is_charged_to_the_turn(monkeypatch):
    from helpers import extension

    class _Slow(extension.Extension):
        async def execute(self, **kwargs):
            await asyncio.sleep(0.05)

    class _Context:
        id = "chat-4"

    class _Agent:
        context = _Context()

    monkeypatch.setattr(extension, "_get_extension_classes", lambda *a, **k: [_Slow])
    perf.turn_start("chat-4")
    await extension.call_extensions_async("system_prompt", _Agent())
    record = perf.turn_end("chat-4")
    assert record["hooks"]["system_prompt"] >= 0.04


def test_latency_for_sums_a_chat_and_background_calls(perf_dir):
    async def run():
        perf.turn_start("chat-5")
        for role in ("main", "main"):
            call = perf.start_model_call("m", role, 400)
            call.slot_acquired()
            call.chunk("r" * 40, "a" * 40)
            call.finish()
        perf.turn_end("chat-5")

    since = time.time() - 1
    asyncio.run(run())
    perf.start_model_call("m", "utility", 0).finish()  # background
    totals = perf.latency_for("chat-5", since)
    assert totals["model_calls"] == 3 and totals["background_calls"] == 1
    assert totals["thinking_tokens_est"] == 20

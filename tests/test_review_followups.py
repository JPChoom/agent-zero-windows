"""Follow-ups from the external review of 2026-11-01 (ChatGPT, v1.5 / v1.5.1):

- background history compression never replaces messages that changed
  while it was summarizing them;
- calls to the local server wait while it restarts with new settings, and a
  turn that starts just before the restart cancels it;
- the turn timing line does not report a "first token" for calls that do
  not stream (their whole duration used to show up as one);
- the local embedding model draws no progress bars;
- the README installs the latest signed release, packages by hash.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest

from helpers import model_concurrency, perf

ROOT = Path(__file__).resolve().parents[1]


# -- compression guard ----------------------------------------------------------------

def test_compression_skips_messages_that_changed_while_summarizing(monkeypatch):
    from helpers import history as history_mod

    class _Agent:
        def parse_prompt(self, name, **kwargs):
            return "SUMMARY " + kwargs.get("summary", "")

    history = history_mod.History.__new__(history_mod.History)
    history.agent = _Agent()
    topic = history_mod.Topic(history=history)
    for i in range(10):
        topic.messages.append(history_mod.Message(bool(i % 2), f"message {i}"))
    original = list(topic.messages)

    async def summarize_while_compressed_elsewhere(messages):
        # meanwhile another pass replaced the oldest messages
        topic.messages[1:4] = [history_mod.Message(False, "someone else's summary")]
        return "stale summary"

    monkeypatch.setattr(topic, "summarize_messages", summarize_while_compressed_elsewhere)
    assert asyncio.run(topic.compress_attention()) is False
    assert all("stale summary" not in str(m.content) for m in topic.messages)

    topic.messages = list(original)

    async def summarize(messages):
        topic.messages.append(history_mod.Message(True, "a new message, appended at the end"))
        return "fresh summary"

    monkeypatch.setattr(topic, "summarize_messages", summarize)
    assert asyncio.run(topic.compress_attention()) is True  # appends do not invalidate it
    assert "fresh summary" in str(topic.messages[1].content)
    assert topic.messages[-1].content == "a new message, appended at the end"


# -- restart gate ---------------------------------------------------------------------------

def test_calls_wait_while_the_server_restarts():
    base = "http://127.0.0.1:8090/v1"

    async def call():
        started = time.monotonic()
        await model_concurrency.wait_for_maintenance("http://localhost:8090/v1/")  # same server
        return time.monotonic() - started

    with model_concurrency.maintenance(base):
        threading.Timer(0.6, lambda: model_concurrency._MAINTENANCE.discard(base)).start()
        waited = asyncio.run(call())
    assert waited >= 0.5
    # other servers and normal times are not delayed
    assert asyncio.run(model_concurrency.wait_for_maintenance("http://127.0.0.1:1234/v1")) is None
    assert asyncio.run(model_concurrency.wait_for_maintenance(None)) is None


def test_a_turn_starting_at_the_last_moment_cancels_the_restart(monkeypatch, tmp_path):
    from extensions.python.job_loop import _40_llama_server as ext
    from helpers import llama_server, local_server

    model = tmp_path / "m.gguf"
    model.write_bytes(b"GGUF")
    monkeypatch.setattr(local_server, "model_config", lambda: {
        "chat_model": {"provider": "lm_studio"},
        "local_server": {**local_server.DEFAULTS, "model_path": str(model), "preset": "balanced"},
    })
    gate_seen = []

    class _Sup:
        stops = 0
        starts = 0

        def status(self):
            return {"state": "running"}

        def running_identity(self):
            return "old-settings"

        def stop(self):
            gate_seen.append(set(model_concurrency._MAINTENANCE))
            _Sup.stops += 1

        def start(self, config):
            _Sup.starts += 1

    monkeypatch.setattr(llama_server, "get", lambda: _Sup())
    checks = iter([False, True])  # idle at the first look, a turn at the second
    monkeypatch.setattr(ext, "_turn_active", lambda: next(checks))
    asyncio.run(ext.LlamaServerAutostart(agent=None).execute())
    assert _Sup.stops == 0 and not model_concurrency._MAINTENANCE  # cancelled, gate open again

    monkeypatch.setattr(ext, "_turn_active", lambda: False)
    asyncio.run(ext.LlamaServerAutostart(agent=None).execute())
    assert _Sup.stops == 1 and _Sup.starts == 1
    assert gate_seen == [{"http://127.0.0.1:8090/v1"}]  # calls were held during the restart
    assert not model_concurrency._MAINTENANCE


# -- timing line ---------------------------------------------------------------------------

def _call(streamed, total=20.9):
    call = perf.ModelCall(model="m", role="utility", context_id="c", prompt_chars=4000, streamed=streamed)
    call.slot_at = call.started
    call.first_chunk_at = call.started + total
    call.ended = call.started + total
    call.response_chars = 400
    return call.as_dict()


def test_calls_that_do_not_stream_report_no_first_token():
    record = _call(streamed=False)
    assert record["first_token_s"] is None and record["streamed"] is False
    assert _call(streamed=True)["first_token_s"] == 20.9

    turn = perf.Turn(context_id="c", agent_name="A0")
    turn.calls = [_call(streamed=False), _call(streamed=False)]
    line = perf.format_turn(perf.summarize_turn(turn, turn.started + 50))
    assert "utility 2x 41.8s (not streamed" in line and "first token" not in line


def test_the_streaming_flag_reaches_the_timing_record():
    source = (ROOT / "models.py").read_text(encoding="utf-8")
    assert "timing.streamed = stream" in source


# -- embeddings ------------------------------------------------------------------------------

def test_the_embedding_model_draws_no_progress_bars(monkeypatch):
    import models

    seen = []

    class _Model:
        def encode(self, texts, **kwargs):
            seen.append(kwargs)
            return [[0.0, 1.0] for _ in texts]

    wrapper = models.LocalSentenceTransformerWrapper.__new__(models.LocalSentenceTransformerWrapper)
    wrapper.model = _Model()
    wrapper.a0_model_conf = None
    monkeypatch.setattr(models, "apply_rate_limiter_sync", lambda *a, **k: None)
    wrapper.embed_documents(["a", "b"])
    wrapper.embed_query("c")
    assert seen and all(k.get("show_progress_bar") is False for k in seen)


# -- README install path ----------------------------------------------------------------------

def test_the_readme_installs_the_signed_release_by_hash():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    install = readme[readme.index("## Install"):readme.index("Run it:")]
    assert "verify-tag $tag" in install and "gpg.ssh.allowedSignersFile=conf/release_signers" in install
    assert "git reset --hard $tag" in install
    assert "--require-hashes -r requirements.lock.txt" in install
    assert "install -r requirements.txt" not in install
    assert (ROOT / "conf" / "release_signers").is_file()

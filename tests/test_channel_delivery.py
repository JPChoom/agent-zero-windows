"""Reliable delivery of agent replies to messaging channels (helpers/channel_delivery.py)."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from helpers import channel_delivery as cd

ROOT = Path(__file__).resolve().parents[1]
NOW = 1_800_000_000.0


class _Log:
    def __init__(self):
        self.items = []

    def log(self, **kwargs):
        self.items.append(kwargs)


def _context(channel_key="telegram_chat_id", context_id="ctx-1"):
    return SimpleNamespace(id=context_id, data={channel_key: "42"}, log=_Log())


class _Sender:
    """A send function that fails with the given errors, then succeeds."""

    def __init__(self, *errors):
        self.errors = list(errors)
        self.calls = []

    async def __call__(self, context, text, attachments):
        self.calls.append((text, list(attachments)))
        error = self.errors.pop(0) if self.errors else ""
        if isinstance(error, BaseException):
            raise error
        return error


class _Clock:
    def __init__(self):
        self.waits = []

    async def sleep(self, seconds):
        self.waits.append(seconds)


@pytest.fixture(autouse=True)
def _outbox(tmp_path, monkeypatch):
    monkeypatch.setattr(cd, "_path", lambda: str(tmp_path / "outbox.json"))
    monkeypatch.setattr(cd.PrintStyle, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(cd.PrintStyle, "error", staticmethod(lambda *a, **k: None))


def run(coro):
    return asyncio.run(coro)


# -- what is worth retrying ----------------------------------------------------

@pytest.mark.parametrize("error,kind", [
    ("Cannot connect to host api.telegram.org:443", "transient"),
    ("TimeoutError: timed out", "transient"),
    ("Too Many Requests: retry after 12", "transient"),
    ("HTTP 503 service unavailable", "transient"),
    ("the Discord bot is not running", "transient"),
    ("451 4.7.1 try again later", "transient"),
    ("something nobody has seen before", "transient"),
    ("Forbidden: bot was blocked by the user", "permanent"),
    ("Bad Request: chat not found", "permanent"),
    ("channel_not_found", "permanent"),
    ("535 5.7.8 Authentication credentials invalid", "permanent"),
    ("550 mailbox unavailable", "permanent"),
    ("Telegram: file not found: x.png", "permanent"),
    ("No chat_id on context", "permanent"),
])
def test_classify(error, kind):
    assert cd.classify(error) == kind


def test_classify_uses_the_exception_class():
    class TelegramRetryAfter(Exception):
        retry_after = 30

    class TelegramForbiddenError(Exception):
        pass

    assert cd.classify(TelegramRetryAfter("flood")) == "transient"
    assert cd.retry_after(TelegramRetryAfter("flood")) == 30
    assert cd.classify(TelegramForbiddenError("anything")) == "permanent"


def test_retry_after_is_read_from_text():
    assert cd.retry_after("Too Many Requests: retry after 12") == 12
    assert cd.retry_after("rate limited, Retry-After: 3.5") == 3.5
    assert cd.retry_after("connection refused") == 0


# -- in-line retries -----------------------------------------------------------

def test_a_good_send_is_not_retried():
    send, clock = _Sender(), _Clock()
    result = run(cd.deliver(_context(), "hi", send=send, sleep=clock.sleep))
    assert result.ok and result.attempts == 1 and clock.waits == [] and cd.pending() == []


def test_a_temporary_failure_is_retried_until_it_works():
    send, clock = _Sender("connection reset", "HTTP 503"), _Clock()
    result = run(cd.deliver(_context(), "hi", send=send, sleep=clock.sleep))
    assert result.ok and result.attempts == 3 and clock.waits == [2.0, 6.0]
    assert cd.pending() == []


def test_the_service_can_ask_for_a_longer_wait():
    send, clock = _Sender("Too Many Requests: retry after 15"), _Clock()
    assert run(cd.deliver(_context(), "hi", send=send, sleep=clock.sleep)).ok
    assert clock.waits == [15.0]


def test_a_very_long_wait_goes_to_the_queue_at_once():
    send, clock = _Sender("Too Many Requests: retry after 900"), _Clock()
    result = run(cd.deliver(_context(), "hi", send=send, sleep=clock.sleep))
    assert not result.ok and result.queued and clock.waits == [] and len(send.calls) == 1


def test_a_permanent_failure_is_not_retried_or_queued():
    send, clock = _Sender("Forbidden: bot was blocked by the user"), _Clock()
    result = run(cd.deliver(_context(), "hi", send=send, sleep=clock.sleep))
    assert not result.ok and result.kind == "permanent" and not result.queued
    assert len(send.calls) == 1 and cd.pending() == []


def test_a_send_that_raises_counts_as_a_failure():
    send, clock = _Sender(ConnectionError("network down")), _Clock()
    assert run(cd.deliver(_context(), "hi", send=send, sleep=clock.sleep)).ok
    assert len(send.calls) == 2


def test_a_reply_that_keeps_failing_is_queued_with_a_note_in_the_chat():
    context = _context()
    send, clock = _Sender(*["connection refused"] * 10), _Clock()
    result = run(cd.deliver(context, "the answer", ["a.txt"], send=send, sleep=clock.sleep))
    assert not result.ok and result.queued and result.attempts == 4
    [entry] = cd.pending()
    assert entry["text"] == "the answer" and entry["attachments"] == ["a.txt"] and entry["channel"] == "telegram"
    assert context.log.items and context.log.items[0]["type"] == "warning"


def test_without_the_queue_a_failure_is_only_reported():
    send, clock = _Sender(*["connection refused"] * 10), _Clock()
    result = run(cd.deliver(_context(), "hi", send=send, sleep=clock.sleep, queue=False))
    assert not result.ok and result.kind == "transient" and not result.queued and cd.pending() == []


def test_a_chat_without_a_channel_has_no_sender():
    result = run(cd.deliver(SimpleNamespace(id="x", data={}, log=_Log()), "hi"))
    assert not result.ok and result.kind == "permanent"


# -- the queue -----------------------------------------------------------------

def test_queuing_the_same_reply_twice_keeps_one():
    context = _context()
    assert cd.enqueue(context, "telegram", "hi", [], "err", now=NOW)
    assert not cd.enqueue(context, "telegram", "hi", [], "err", now=NOW)
    assert len(cd.pending()) == 1


def test_the_queue_is_capped_and_keeps_the_newest(monkeypatch):
    monkeypatch.setattr(cd, "QUEUE_MAX_ENTRIES", 3)
    for i in range(5):
        cd.enqueue(_context(context_id=f"c{i}"), "telegram", f"m{i}", [], "err", now=NOW + i)
    assert [e["text"] for e in cd.pending()] == ["m2", "m3", "m4"]


def test_an_unreadable_queue_is_set_aside_not_lost(tmp_path):
    (tmp_path / "outbox.json").write_text("{not json", encoding="utf-8")
    assert cd.pending() == []
    assert (tmp_path / "outbox.json.bad").exists()
    assert cd.enqueue(_context(), "telegram", "hi", [], "err", now=NOW)


def _drain(contexts, now=NOW, send=None):
    from agent import AgentContext

    original = AgentContext.get
    AgentContext.get = staticmethod(lambda cid: contexts.get(cid))
    try:
        return run(cd.drain(now=now, send=send))
    finally:
        AgentContext.get = original


def test_drain_waits_for_a_reply_that_is_not_due():
    context = _context()
    cd.enqueue(context, "telegram", "hi", [], "err", now=NOW)
    send = _Sender()
    assert _drain({"ctx-1": context}, now=NOW + 10, send=send) == {"delivered": 0, "dropped": 0, "waiting": 1}
    assert send.calls == []


def test_drain_delivers_a_due_reply_and_tells_the_chat():
    context = _context()
    cd.enqueue(context, "telegram", "hi", [], "err", now=NOW)
    send = _Sender()
    stats = _drain({"ctx-1": context}, now=NOW + cd.QUEUE_DELAYS[0] + 1, send=send)
    assert stats["delivered"] == 1 and cd.pending() == [] and send.calls == [("hi", [])]
    assert context.log.items[-1]["type"] == "info"


def test_drain_reschedules_a_reply_that_still_fails_with_growing_gaps():
    context = _context()
    cd.enqueue(context, "telegram", "hi", [], "err", now=NOW)
    send = _Sender(*["connection refused"] * 5)
    t = NOW + cd.QUEUE_DELAYS[0] + 1
    gaps = []
    for _ in range(3):
        assert _drain({"ctx-1": context}, now=t, send=send)["waiting"] == 1
        [entry] = cd.pending()
        gaps.append(entry["next_try"] - t)
        t = entry["next_try"] + 1
    assert gaps == [cd.QUEUE_DELAYS[1], cd.QUEUE_DELAYS[2], cd.QUEUE_DELAYS[3]] and gaps == sorted(gaps)


def test_drain_drops_a_reply_that_turns_out_to_be_permanent():
    context = _context()
    cd.enqueue(context, "telegram", "hi", [], "err", now=NOW)
    stats = _drain({"ctx-1": context}, now=NOW + 100, send=_Sender("Forbidden: bot was blocked by the user"))
    assert stats["dropped"] == 1 and cd.pending() == []
    assert context.log.items[-1]["type"] == "error"


def test_drain_gives_up_on_an_old_reply():
    context = _context()
    cd.enqueue(context, "telegram", "hi", [], "err", now=NOW)
    stats = _drain({"ctx-1": context}, now=NOW + cd.QUEUE_MAX_AGE + 10, send=_Sender("connection refused"))
    assert stats["dropped"] == 1 and cd.pending() == []


def test_drain_drops_a_reply_for_a_deleted_chat():
    cd.enqueue(_context(), "telegram", "hi", [], "err", now=NOW)
    assert _drain({}, now=NOW + 100, send=_Sender())["dropped"] == 1


def test_drain_skips_attachments_that_are_gone(tmp_path):
    context, kept = _context(), tmp_path / "kept.txt"
    kept.write_text("x", encoding="utf-8")
    cd.enqueue(context, "telegram", "hi", [str(kept), str(tmp_path / "gone.txt")], "err", now=NOW)
    send = _Sender()
    _drain({"ctx-1": context}, now=NOW + 100, send=send)
    assert send.calls == [("hi", [str(kept)])]


def test_a_reply_queued_while_draining_is_kept():
    first, second = _context(context_id="c1"), _context(context_id="c2")
    cd.enqueue(first, "telegram", "one", [], "err", now=NOW)

    async def send(context, text, attachments):
        cd.enqueue(second, "telegram", "two", [], "err", now=NOW)  # another thread queues meanwhile
        return ""

    _drain({"c1": first, "c2": second}, now=NOW + 100, send=send)
    assert [e["text"] for e in cd.pending()] == ["two"]


def test_the_queue_survives_a_restart(tmp_path):
    cd.enqueue(_context(), "telegram", "hi", [], "err", now=NOW)
    on_disk = json.loads((tmp_path / "outbox.json").read_text(encoding="utf-8"))
    assert on_disk[0]["context_id"] == "ctx-1" and on_disk[0]["text"] == "hi"
    assert len(cd.pending()) == 1  # a fresh read, as after a restart


# -- wiring ------------------------------------------------------------------------

SEND_SITES = [
    "plugins/_telegram_integration/extensions/python/process_chain_end/_55_telegram_reply.py",
    "plugins/_telegram_integration/extensions/python/tool_execute_after/_50_telegram_response.py",
    "plugins/_telegram_integration/extensions/python/_functions/agent/Agent/handle_exception/end/_85_telegram_error.py",
    "plugins/_whatsapp_integration/extensions/python/process_chain_end/_55_wa_reply.py",
    "plugins/_whatsapp_integration/extensions/python/tool_execute_after/_50_wa_response.py",
    "plugins/_email_integration/extensions/python/process_chain_end/_55_email_reply.py",
    "plugins/_email_integration/extensions/python/tool_execute_after/_50_email_response.py",
    "plugins/_discord_integration/extensions/python/process_chain_end/_55_discord_reply.py",
    "plugins/_discord_integration/extensions/python/tool_execute_after/_50_discord_response.py",
    "plugins/_slack_integration/extensions/python/process_chain_end/_55_slack_reply.py",
    "plugins/_slack_integration/extensions/python/tool_execute_after/_50_slack_response.py",
]


@pytest.mark.parametrize("path", SEND_SITES)
def test_every_send_site_goes_through_deliver(path):
    source = (ROOT / path).read_text(encoding="utf-8")
    assert "channel_delivery.deliver(" in source, path
    for direct in ("= await bot.send_reply(", "= await send_telegram_reply(", "= await send_wa_reply(", "= await send_email_reply("):
        assert direct not in source, f"{path} still sends directly: {direct}"


def test_telegram_text_sends_raise_so_a_failure_is_not_a_success():
    source = (ROOT / "plugins/_telegram_integration/helpers/handler.py").read_text(encoding="utf-8")
    assert source.count("raise_errors=True") == 2
    client = (ROOT / "plugins/_telegram_integration/helpers/telegram_client.py").read_text(encoding="utf-8")
    assert client.count("raise_errors: bool = False") == 2 and client.count("if raise_errors:") == 2


def test_telegram_send_text_raises_when_asked():
    pytest.importorskip("aiogram")
    from plugins._telegram_integration.helpers import telegram_client as tc

    class Bot:
        async def send_message(self, **kwargs):
            raise ConnectionError("network down")

    assert run(tc.send_text(Bot(), 1, "hi")) is None
    with pytest.raises(ConnectionError):
        run(tc.send_text(Bot(), 1, "hi", raise_errors=True))


def test_the_job_loop_drains_the_queue(monkeypatch):
    import importlib

    module = importlib.import_module("extensions.python.job_loop._35_channel_outbox")
    seen = []

    async def fake_drain(*a, **k):
        seen.append(True)

    monkeypatch.setattr(cd, "drain", fake_drain)
    run(module.DrainChannelOutbox(agent=None).execute())
    assert seen == [True]


def test_approval_questions_retry_quickly_and_are_never_queued(monkeypatch):
    from helpers import channel_approvals as ca

    seen = {}

    async def fake_deliver(context, text, attachments=None, **kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(cd, "deliver", fake_deliver)
    run(ca._deliver_question(_context(), "q"))
    assert seen["queue"] is False and seen["delays"] == (2.0, 6.0)

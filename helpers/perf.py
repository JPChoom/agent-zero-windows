"""Latency measurement for the local-speed work (v1.4 part 2, item 0).

Records where the time of a turn goes, so speed changes can be judged by
numbers instead of impressions: every model call (how long it queued for
the backend, time to the first token, generation speed, hidden reasoning),
every extension hook, every tool, and event-loop stalls.

Only numbers, model names and chat ids are recorded - never prompt or
response text. Records go to `usr/perf/model_calls.jsonl` and
`usr/perf/turns.jsonl` (git-ignored user state, capped in size) and a
one-line summary is printed at the end of each turn.

Token counts are estimates (characters / 4): the backends do not report
usage on every streaming path. Good enough to compare runs on one PC.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import os
import threading
import time
import weakref
from dataclasses import dataclass, field
from typing import Any

# Chat id of the turn running in the current task. Set when a turn starts;
# tasks created from that turn inherit it. Background work on its own thread
# (memorize, deferred tasks) has no turn and is recorded as background.
CONTEXT_ID: contextvars.ContextVar[str] = contextvars.ContextVar("a0_perf_context_id", default="")

PERF_DIR_PARTS = ("usr", "perf")
MAX_LOG_BYTES = 5 * 1024 * 1024
LOOP_PROBE_SECONDS = 0.1
CHARS_PER_TOKEN = 4

_lock = threading.RLock()
_enabled = True


def set_enabled(value: bool) -> None:
    global _enabled
    _enabled = bool(value)


def is_enabled() -> bool:
    return _enabled


def estimate_tokens(chars: int) -> int:
    return (max(0, int(chars)) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


# --------------------------------------------------------------------------
# model calls
# --------------------------------------------------------------------------

@dataclass
class ModelCall:
    model: str
    role: str
    context_id: str
    prompt_chars: int
    started: float = field(default_factory=time.monotonic)
    slot_at: float | None = None
    first_chunk_at: float | None = None
    ended: float | None = None
    reasoning_chars: int = 0
    response_chars: int = 0
    attempts: int = 0
    ok: bool = True
    error: str = ""

    def slot_acquired(self) -> None:
        self.attempts += 1
        if self.slot_at is None:
            self.slot_at = time.monotonic()

    def chunk(self, reasoning_delta: str, response_delta: str) -> None:
        if self.first_chunk_at is None and (reasoning_delta or response_delta):
            self.first_chunk_at = time.monotonic()
        self.reasoning_chars += len(reasoning_delta or "")
        self.response_chars += len(response_delta or "")

    def finish(self, error: BaseException | None = None) -> dict[str, Any]:
        self.ended = time.monotonic()
        if error is not None:
            self.ok = False
            self.error = type(error).__name__
        record = self.as_dict()
        _record_call(record)
        return record

    def as_dict(self) -> dict[str, Any]:
        end = self.ended or time.monotonic()
        slot = self.slot_at or end
        first = self.first_chunk_at
        out_tokens = estimate_tokens(self.reasoning_chars + self.response_chars)
        gen_seconds = (end - first) if first is not None else 0.0
        return {
            "ts": time.time(),
            "model": self.model,
            "role": self.role,
            "context_id": self.context_id,
            "background": not self.context_id,
            "queue_wait_s": round(slot - self.started, 3),
            "first_token_s": round(first - slot, 3) if first is not None else None,
            "total_s": round(end - self.started, 3),
            "prompt_tokens_est": estimate_tokens(self.prompt_chars),
            "reasoning_tokens_est": estimate_tokens(self.reasoning_chars),
            "response_tokens_est": estimate_tokens(self.response_chars),
            "tokens_per_s": round(out_tokens / gen_seconds, 1) if gen_seconds > 0.05 else None,
            "attempts": self.attempts,
            "ok": self.ok,
            "error": self.error,
        }


def start_model_call(model: str, role: str, prompt_chars: int) -> ModelCall:
    return ModelCall(model=str(model), role=role or "other", context_id=CONTEXT_ID.get(), prompt_chars=prompt_chars)


# --------------------------------------------------------------------------
# turns
# --------------------------------------------------------------------------

@dataclass
class Turn:
    context_id: str
    agent_name: str
    started: float = field(default_factory=time.monotonic)
    calls: list[dict[str, Any]] = field(default_factory=list)
    hooks: dict[str, float] = field(default_factory=dict)
    extensions: dict[str, float] = field(default_factory=dict)
    tools: list[tuple[str, float]] = field(default_factory=list)
    loop_stall_max_s: float = 0.0
    loop_stalls: int = 0


_turns: dict[str, Turn] = {}


def turn_start(context_id: str, agent_name: str = "") -> None:
    if not _enabled or not context_id:
        return
    with _lock:
        _turns[context_id] = Turn(context_id=context_id, agent_name=agent_name)
    CONTEXT_ID.set(context_id)
    _ensure_loop_monitor()
    _reset_loop_stats()


def _turn(context_id: str) -> Turn | None:
    if not context_id:
        return None
    return _turns.get(context_id)


def add_hook_time(context_id: str, hook: str, extension: str, seconds: float) -> None:
    if not _enabled:
        return
    with _lock:
        turn = _turn(context_id)
        if turn is None:
            return
        turn.hooks[hook] = turn.hooks.get(hook, 0.0) + seconds
        turn.extensions[extension] = turn.extensions.get(extension, 0.0) + seconds


def add_tool_time(context_id: str, tool: str, seconds: float) -> None:
    if not _enabled:
        return
    with _lock:
        turn = _turn(context_id)
        if turn is not None:
            turn.tools.append((tool, seconds))


def turn_end(context_id: str) -> dict[str, Any] | None:
    """Close the turn, write its record and return it (None if none ran)."""
    with _lock:
        turn = _turns.pop(context_id, None)
    if turn is None:
        return None
    stall_max, stalls = _read_loop_stats()
    turn.loop_stall_max_s = stall_max
    turn.loop_stalls = stalls
    record = summarize_turn(turn, time.monotonic())
    _append_jsonl("turns.jsonl", record)
    return record


def summarize_turn(turn: Turn, now: float) -> dict[str, Any]:
    by_role: dict[str, dict[str, Any]] = {}
    for call in turn.calls:
        role = by_role.setdefault(call["role"], {
            "calls": 0, "total_s": 0.0, "queue_wait_s": 0.0, "first_token_s": 0.0,
            "reasoning_tokens_est": 0, "response_tokens_est": 0, "prompt_tokens_est": 0,
        })
        role["calls"] += 1
        role["total_s"] += call["total_s"]
        role["queue_wait_s"] += call["queue_wait_s"]
        role["first_token_s"] += call["first_token_s"] or 0.0
        role["reasoning_tokens_est"] += call["reasoning_tokens_est"]
        role["response_tokens_est"] += call["response_tokens_est"]
        role["prompt_tokens_est"] += call["prompt_tokens_est"]
    for role in by_role.values():
        for key in ("total_s", "queue_wait_s", "first_token_s"):
            role[key] = round(role[key], 3)
    slowest = sorted(turn.extensions.items(), key=lambda item: item[1], reverse=True)[:5]
    return {
        "ts": time.time(),
        "context_id": turn.context_id,
        "agent": turn.agent_name,
        "total_s": round(now - turn.started, 3),
        "models": by_role,
        "tools_s": round(sum(seconds for _, seconds in turn.tools), 3),
        "tools": [{"tool": name, "s": round(seconds, 3)} for name, seconds in turn.tools],
        "hooks_s": round(sum(turn.hooks.values()), 3),
        "hooks": {name: round(seconds, 3) for name, seconds in sorted(turn.hooks.items())},
        "slowest_extensions": [{"extension": name, "s": round(seconds, 3)} for name, seconds in slowest],
        "loop_stall_max_s": round(turn.loop_stall_max_s, 3),
        "loop_stalls_over_100ms": turn.loop_stalls,
    }


def format_turn(record: dict[str, Any]) -> str:
    """One line a person can read: where did this turn's time go."""
    parts = [f"Turn {record['total_s']:.1f}s"]
    for role, stats in sorted(record["models"].items()):
        piece = f"{role} {stats['calls']}x {stats['total_s']:.1f}s"
        details = []
        if stats["queue_wait_s"] >= 0.1:
            details.append(f"waited {stats['queue_wait_s']:.1f}s")
        if stats["first_token_s"]:
            details.append(f"first token {stats['first_token_s']:.1f}s")
        if stats["reasoning_tokens_est"]:
            details.append(f"thinking ~{stats['reasoning_tokens_est']} tok")
        details.append(f"answer ~{stats['response_tokens_est']} tok")
        parts.append(piece + " (" + ", ".join(details) + ")")
    parts.append(f"tools {record['tools_s']:.1f}s")
    parts.append(f"hooks {record['hooks_s']:.1f}s")
    if record["slowest_extensions"] and record["slowest_extensions"][0]["s"] >= 0.2:
        top = record["slowest_extensions"][0]
        parts.append(f"slowest hook {top['extension']} {top['s']:.1f}s")
    if record["loop_stall_max_s"] >= 0.1:
        parts.append(f"UI stalled up to {record['loop_stall_max_s'] * 1000:.0f}ms")
    return " | ".join(parts)


def _record_call(record: dict[str, Any]) -> None:
    if not _enabled:
        return
    with _lock:
        turn = _turn(record["context_id"])
        if turn is not None:
            turn.calls.append(record)
    _append_jsonl("model_calls.jsonl", record)


# --------------------------------------------------------------------------
# event-loop stalls
# --------------------------------------------------------------------------
# A probe sleeps LOOP_PROBE_SECONDS and measures how late it wakes up. Being
# late means something ran on the loop without yielding - and while it ran,
# every chat, websocket and request on that loop waited.

_loop_monitors: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Task]" = weakref.WeakKeyDictionary()
_loop_stats: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, list[float]]" = weakref.WeakKeyDictionary()


def _ensure_loop_monitor() -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = _loop_monitors.get(loop)
    if task is not None and not task.done():
        return
    _loop_stats[loop] = [0.0, 0.0]
    _loop_monitors[loop] = loop.create_task(_probe_loop(loop), name="a0-perf-loop-probe")


async def _probe_loop(loop: asyncio.AbstractEventLoop) -> None:
    while True:
        before = time.monotonic()
        await asyncio.sleep(LOOP_PROBE_SECONDS)
        lag = time.monotonic() - before - LOOP_PROBE_SECONDS
        stats = _loop_stats.get(loop)
        if stats is None:
            continue
        if lag > stats[0]:
            stats[0] = lag
        if lag > 0.1:
            stats[1] += 1


def _reset_loop_stats() -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if loop in _loop_stats:
        _loop_stats[loop] = [0.0, 0.0]


def _read_loop_stats() -> tuple[float, int]:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return 0.0, 0
    stats = _loop_stats.get(loop) or [0.0, 0.0]
    return stats[0], int(stats[1])


# --------------------------------------------------------------------------
# storage
# --------------------------------------------------------------------------

def perf_dir() -> str:
    from helpers import files

    return files.get_abs_path(*PERF_DIR_PARTS)


def _append_jsonl(name: str, record: dict[str, Any]) -> None:
    try:
        folder = perf_dir()
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        line = json.dumps(record, separators=(",", ":")) + "\n"
        with _lock:
            if os.path.exists(path) and os.path.getsize(path) > MAX_LOG_BYTES:
                os.replace(path, path + ".1")
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line)
    except Exception:
        # Measurement must never break a turn.
        pass


def read_records(name: str, since: float = 0.0) -> list[dict[str, Any]]:
    """Records from one of the JSONL files written at or after `since` (epoch s)."""
    path = os.path.join(perf_dir(), name)
    records: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record.get("ts", 0) >= since:
                    records.append(record)
    except OSError:
        pass
    return records


def latency_for(context_id: str, since: float) -> dict[str, Any]:
    """Latency totals for one chat since `since`, including the background
    calls made in that window (they compete for the same model)."""
    calls = [
        c for c in read_records("model_calls.jsonl", since)
        if c.get("context_id") == context_id or c.get("background")
    ]
    turns = [t for t in read_records("turns.jsonl", since) if t.get("context_id") == context_id]
    first_tokens = sorted(c["first_token_s"] for c in calls if c.get("first_token_s") is not None)
    return {
        "model_calls": len(calls),
        "background_calls": sum(1 for c in calls if c.get("background")),
        "model_s": round(sum(c.get("total_s", 0.0) for c in calls), 1),
        "queue_wait_s": round(sum(c.get("queue_wait_s", 0.0) for c in calls), 1),
        "median_first_token_s": first_tokens[len(first_tokens) // 2] if first_tokens else None,
        "thinking_tokens_est": sum(c.get("reasoning_tokens_est", 0) for c in calls),
        "answer_tokens_est": sum(c.get("response_tokens_est", 0) for c in calls),
        "tools_s": round(sum(t.get("tools_s", 0.0) for t in turns), 1),
        "hooks_s": round(sum(t.get("hooks_s", 0.0) for t in turns), 1),
        "loop_stall_max_s": max((t.get("loop_stall_max_s", 0.0) for t in turns), default=0.0),
    }

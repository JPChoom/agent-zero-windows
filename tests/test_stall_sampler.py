"""A blocked event loop leaves a record of what it was doing."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import time
from pathlib import Path

from helpers import perf

ROOT = Path(__file__).resolve().parents[1]


def _block_the_loop(seconds):
    time.sleep(seconds)  # deliberately synchronous: the stall being sampled


def test_a_stall_is_recorded_with_its_stack(tmp_path, monkeypatch):
    monkeypatch.setattr(perf, "perf_dir", lambda: str(tmp_path))
    monkeypatch.setattr(perf, "_heartbeats", {})

    async def run():
        perf._ensure_loop_monitor()
        await asyncio.sleep(0.3)  # the probe beats
        _block_the_loop(1.2)
        await asyncio.sleep(0.4)  # the loop runs again: the stall is written

    asyncio.run(run())
    rows = [json.loads(line) for line in (tmp_path / "stalls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows and rows[0]["seconds"] >= 1.0
    assert any("_block_the_loop" in frame for frame in rows[0]["stack"])
    assert all(":" in frame for frame in rows[0]["stack"])


def test_short_waits_are_not_stalls(tmp_path, monkeypatch):
    monkeypatch.setattr(perf, "perf_dir", lambda: str(tmp_path))
    monkeypatch.setattr(perf, "_heartbeats", {})

    async def run():
        perf._ensure_loop_monitor()
        for _ in range(5):
            await asyncio.sleep(0.1)

    asyncio.run(run())
    assert not (tmp_path / "stalls.jsonl").exists()


def test_the_report_names_the_deepest_own_frame():
    spec = importlib.util.spec_from_file_location("report", ROOT / "tests/manual/stall_report.py")
    report = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(report)
    stack = ["asyncio/base_events.py:1 run", "agent.py:500 stream_callback", "helpers/dirty_json.py:40 parse", "json/decoder.py:9 decode"]
    assert report.culprit(stack) == "helpers/dirty_json.py:40 parse"
    rows = [{"seconds": 2, "stack": stack}, {"seconds": 1, "stack": stack}, {"seconds": 5, "stack": ["x.py:1 f"]}]
    assert report.summarize(rows)[0] == ("x.py:1 f", 1, 5.0, 5.0)

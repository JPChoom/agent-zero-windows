"""A looping reply is stopped, long replies stay fast, and the timing line tells
waiting for a person apart from work."""

from __future__ import annotations

import asyncio
import json
import random
import time
from types import SimpleNamespace

import pytest

from helpers import extract_tools, perf, runaway_guard
from helpers.dirty_json import DirtyJson

HEAD = '{"thoughts": ["Write the script."], "headline": "Scan", "tool_name": "code_execution_tool", "tool_args": {"runtime": "python", "code": "VENDORS = {\\n'


def _table(rows):
    return HEAD + "".join(f'    \\"00-{i // 256 % 256:02X}-{i % 256:02X}\\": \\"Apple\\",\\n' for i in range(rows))


def _code(lines):
    rng = random.Random(3)
    words = ["total", "result", "items", "client", "render", "update", "config", "values", "session", "buffer"]
    return "\n".join(f"def {rng.choice(words)}_{i}({rng.choice(words)}, {rng.choice(words)}): return {rng.choice(words)} + {i}" for i in range(lines))


# -- the guard ----------------------------------------------------------------

def test_a_made_up_table_is_caught():
    assert runaway_guard.is_repeating(_table(1200))


def test_the_same_sentence_on_one_line_is_caught():
    assert runaway_guard.is_repeating("I will now check the file again to be sure about it. " * 800)


def _prose(paragraphs):
    words = ["red", "green", "blue", "north", "south", "river", "stone"]
    return "\n".join(f"Paragraph {i}: " + " ".join(random.Random(i).choices(words, k=14)) for i in range(paragraphs))


@pytest.mark.parametrize("make,size", [(_table, 100), (_code, 1500), (_prose, 800)], ids=["short", "code", "prose"])
def test_normal_long_text_is_left_alone(make, size):
    assert not runaway_guard.is_repeating(make(size))


def _agent():
    return SimpleNamespace(intervention=None, loop_data=SimpleNamespace(params_temporary={}))


def test_a_repeating_stream_is_told_to_stop_once():
    agent = _agent()
    runaway_guard.check(agent, {"full": _table(1200)})
    assert "Automatic stop" in agent.intervention.message
    first = agent.intervention
    runaway_guard.check(agent, {"full": _table(1300)})
    assert agent.intervention is first


def test_a_users_own_message_is_not_replaced():
    agent = _agent()
    agent.intervention = "user's message"
    runaway_guard.check(agent, {"full": _table(1200)})
    assert agent.intervention == "user's message"


def test_the_check_only_runs_every_so_often():
    agent = _agent()
    agent.loop_data.params_temporary[runaway_guard._CHECKED_KEY] = len(_table(1200))
    runaway_guard.check(agent, {"full": _table(1201)})  # a little more text
    assert agent.intervention is None


def test_a_new_shorter_reply_starts_over():
    agent = _agent()
    agent.loop_data.params_temporary[runaway_guard._CHECKED_KEY] = 500000
    runaway_guard.check(agent, {"full": _table(1200)})
    assert agent.intervention is not None


def test_short_replies_and_missing_loop_data_are_ignored():
    agent = _agent()
    runaway_guard.check(agent, {"full": "short"})
    runaway_guard.check(SimpleNamespace(intervention=None, loop_data=None), {"full": _table(1200)})
    runaway_guard.check(agent, None)
    assert agent.intervention is None and not agent.loop_data.params_temporary


# -- parsing ------------------------------------------------------------------

def test_a_long_unfinished_reply_costs_nothing_per_token():
    text = _table(3000)
    started = time.perf_counter()
    for _ in range(200):
        assert extract_tools.extract_tool_request(text) is None
    assert time.perf_counter() - started < 0.5


CALLS = [
    '{"thoughts": ["x"], "tool_name": "response", "tool_args": {"text": "done"}}',
    'Running it now:\n{"thoughts": ["x"], "tool_name": "code_execution_tool", "tool_args": {"code": "a = {1: 2}"}}',
    '<tool_call>{"thoughts": ["x"], "tool_name": "response", "tool_args": {"text": "hi"}}</tool_call>',
    '<tool_call>{"thoughts": ["x"], "tool_name": "response", "tool_args": {"text": "hi"}</tool_call>',
    '{"thoughts": ["a", "tool_name": "response", "tool_args": {"text": "unclosed thoughts"}}',
]


@pytest.mark.parametrize("call", CALLS)
def test_a_finished_call_is_still_found(call):
    assert extract_tools.extract_tool_request(call) is not None
    assert extract_tools.extract_tool_request(call + "\n  ") is not None


@pytest.mark.parametrize("call", CALLS)
def test_a_call_is_only_found_at_its_end(call):
    for size in range(1, len(call) - 12):
        part = call[:size]
        if not part.rstrip().endswith(("}", ">")):
            assert extract_tools.extract_tool_request(part) is None


@pytest.mark.parametrize("text", [
    r'{"a": "plain \"quoted\" and \\ back\nslash", "b": "tab\there"}',
    r"{'a': 'single \'quoted\' text', 'b': 'it''s'}",
    '{"a": "é ü 中文 😀", "b": "\\u00e9"}',
    '{"a": "unterminated string',
    '{"a": "line\nbreak inside", "b": 1}',
    '{"code": "if x: {\\"k\\": \\"v\\"}"}',
])
def test_strings_parse_the_same_as_the_standard_parser_where_it_can(text):
    result = DirtyJson.parse_string(text)
    try:
        assert result == json.loads(text)
    except ValueError:
        assert isinstance(result, dict)


def test_a_long_string_parses_whole():
    text = "x" * 50000 + ' "quoted" ' + "y" * 50000
    assert DirtyJson.parse_string(json.dumps({"a": text})) == {"a": text}


# -- the timing line ----------------------------------------------------------

def test_a_wait_for_a_person_is_not_hook_time(tmp_path, monkeypatch):
    monkeypatch.setattr(perf, "perf_dir", lambda: str(tmp_path))

    async def run():
        perf.CONTEXT_ID.set("chat-wait")
        perf.turn_start("chat-wait", "A0")
        box = [0.0]
        token = perf.HOOK_USER_WAIT.set(box)
        with perf.waiting_for_user():
            await asyncio.sleep(0.05)
        perf.HOOK_USER_WAIT.reset(token)
        return box[0], perf.turn_end("chat-wait")

    waited, record = asyncio.run(run())
    assert waited >= 0.04 and record["user_wait_s"] >= 0.04
    assert perf.format_turn({**record, "user_wait_s": 178.0}).count("waiting for you 178.0s") == 1


def test_an_extensions_hook_time_leaves_the_wait_out(tmp_path, monkeypatch):
    from helpers import extension

    charged = []
    monkeypatch.setattr(perf, "add_hook_time", lambda ctx, point, name, seconds: charged.append(seconds))
    monkeypatch.setattr(extension, "_perf_context_id", lambda agent: "chat")

    class Waits:
        FAIL_LOUD = False

        def __init__(self, agent=None):
            pass

        async def execute(self, **kwargs):
            with perf.waiting_for_user():
                await asyncio.sleep(0.2)

    monkeypatch.setattr(extension, "_get_extension_classes", lambda *a, **k: [Waits])
    asyncio.run(extension.call_extensions_async("test_point", None))
    assert charged and charged[0] < 0.1


def test_no_wait_shows_nothing():
    record = {"models": {}, "tools_s": 0, "hooks_s": 0, "slowest_extensions": [], "loop_stall_max_s": 0, "total_s": 1, "user_wait_s": 0.0}
    assert "waiting for you" not in perf.format_turn(record)

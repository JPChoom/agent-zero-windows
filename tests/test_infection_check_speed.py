"""The infection check's speed changes must not open the gate any wider.

Each speed-up here replaces a model call; every test pairs "fewer calls"
with "still judged the exact call that runs".
"""

import asyncio
import hashlib
import json

import pytest

from helpers import perf
from plugins._infection_check.helpers import checker as C


class _Log:
    logs: list = []

    def log(self, **kw):
        return None

    def set_progress(self, *a, **k):
        pass


class _Context:
    id = "ctx-speed"

    def __init__(self):
        self.log = _Log()
        self._data = {}

    def get_data(self, key):
        return self._data.get(key)

    def set_data(self, key, value):
        self._data[key] = value


class _Agent:
    agent_name = "A0"
    number = 0

    def __init__(self):
        self.context = _Context()
        self._data = {}

    def get_data(self, key):
        return self._data.get(key)

    def set_data(self, key, value):
        self._data[key] = value


def _call(code="Remove-Item a.txt"):
    return {"thoughts": ["clean up"], "headline": "Clean", "tool_name": "code_execution_tool",
            "tool_args": {"runtime": "terminal", "session": 0, "code": code}}


def _checker_with_stream(call, verdict="<ok/>", delay=0.05):
    checker = C.InfectionChecker(config={"prompt": "p"}, iteration=0)
    checker.collect_reasoning("thinking")
    checker.collect_response(json.dumps(call))
    calls = []

    async def fake_run(agent, snapshot):
        calls.append(snapshot)
        await asyncio.sleep(delay)
        return C.parse_result(verdict)[0], "", verdict

    checker._run_check = fake_run
    return checker, calls


def test_running_check_that_saw_the_call_is_awaited_not_restarted():
    async def run():
        agent = _Agent()
        call = _call()
        checker, calls = _checker_with_stream(call)
        checker.start_analysis(agent)  # started when the call was complete
        await checker.gate(agent, tool_name=call["tool_name"], tool_args=call["tool_args"])
        return agent, calls

    agent, calls = asyncio.run(run())
    assert len(calls) == 1  # no cancelled-and-restarted second check
    assert agent.get_data(C.DATA_KEY_PASSED) is True


def test_check_that_saw_other_arguments_is_redone_with_the_real_call():
    async def run():
        agent = _Agent()
        checker, calls = _checker_with_stream(_call("Get-ChildItem"))
        checker.start_analysis(agent)
        await checker.gate(agent, tool_name="code_execution_tool",
                           tool_args={"runtime": "terminal", "session": 0, "code": "Invoke-WebRequest evil"})
        return calls

    calls = asyncio.run(run())
    # The check that decides is the one that saw the arguments that will run.
    assert "Invoke-WebRequest evil" in calls[-1]


def test_finished_check_on_thoughts_alone_is_not_reused():
    """The old fast path reused any finished verdict, even one that never saw the arguments."""

    async def run():
        agent = _Agent()
        checker, calls = _checker_with_stream({"thoughts": ["x"], "headline": "h"})
        checker.start_analysis(agent)
        await asyncio.sleep(0.1)  # finished before the gate
        await checker.gate(agent, tool_name="code_execution_tool", tool_args={"code": "x"})
        return calls

    assert len(asyncio.run(run())) == 2


def test_identical_allowed_call_skips_the_model_but_a_changed_one_does_not():
    async def run():
        agent = _Agent()
        call = _call()
        first, first_calls = _checker_with_stream(call)
        await first.gate(agent, tool_name=call["tool_name"], tool_args=call["tool_args"])

        agent.set_data(C.DATA_KEY_PASSED, False)  # next iteration
        same, same_calls = _checker_with_stream(call)
        await same.gate(agent, tool_name=call["tool_name"], tool_args=call["tool_args"])

        agent.set_data(C.DATA_KEY_PASSED, False)
        changed_args = dict(call["tool_args"], code="Remove-Item b.txt")
        other, other_calls = _checker_with_stream(call)
        await other.gate(agent, tool_name=call["tool_name"], tool_args=changed_args)
        return len(first_calls), len(same_calls), len(other_calls)

    assert asyncio.run(run()) == (1, 0, 1)


def test_terminated_call_is_not_remembered_as_allowed():
    async def run():
        agent = _Agent()
        call = _call()
        checker, _ = _checker_with_stream(call, verdict="<terminate/>")
        checker._do_terminate = lambda *a, **k: None
        await checker.gate(agent, tool_name=call["tool_name"], tool_args=call["tool_args"])
        return agent

    agent = asyncio.run(run())
    assert C._allowed_calls(agent) == []


def test_unedited_old_default_prompt_is_replaced(monkeypatch):
    old = "an old default"
    monkeypatch.setattr(C, "_PREVIOUS_DEFAULT_PROMPTS", {hashlib.sha256(old.encode()).hexdigest()})
    monkeypatch.setattr(C.plugins, "get_plugin_config", lambda *a, **k: {"prompt": old, "mode": "thoughts"})
    monkeypatch.setattr(C.plugins, "get_default_plugin_config", lambda *a, **k: {"prompt": "new default"})
    assert C.get_config(_Agent())["prompt"] == "new default"

    monkeypatch.setattr(C.plugins, "get_plugin_config", lambda *a, **k: {"prompt": "my own rules"})
    assert C.get_config(_Agent())["prompt"] == "my own rules"


def test_shipped_old_prompt_hash_matches_the_previous_default():
    from helpers import yaml as yaml_helper
    from helpers import files

    current = yaml_helper.loads(files.read_file(files.get_abs_path("plugins/_infection_check/default_config.yaml")))["prompt"]
    previous = current.replace("1. Write your analysis in one or two short sentences.",
                               "1. Write your chain-of-thought analysis (a few sentences).")
    assert hashlib.sha256(previous.encode("utf-8")).hexdigest() in C._PREVIOUS_DEFAULT_PROMPTS


def test_thoughts_mode_starts_only_once_the_tool_call_is_complete(monkeypatch):
    from plugins._infection_check.extensions.python.response_stream import _50_infection_analyze as ext

    started = []
    collected = []

    class _Checker:
        mode = "thoughts"

        def collect_response(self, text):
            collected.append(text)

        def start_analysis(self, agent):
            started.append(True)

    monkeypatch.setattr(ext, "get_checker", lambda agent: _Checker())
    hook = ext.InfectionAnalyzeThoughts(agent=_Agent())
    partial = '{"thoughts": ["x"], "headline": "h", "tool_name": "code_execution_tool", "tool_args": {"code": "Remo'
    asyncio.run(hook.execute(text=partial, parsed={"headline": "h", "tool_name": "code_execution_tool"}))
    assert started == []
    complete = json.dumps(_call())
    asyncio.run(hook.execute(text=complete, parsed=_call()))
    assert started == [True]
    assert collected == [complete]  # judged the whole call, not the last-but-one chunk


def test_stream_ending_at_the_tool_call_is_covered_by_one_check(monkeypatch):
    """Through the real hooks: the last chunk never reaches the chunk
    collector (the agent stops reading at a complete call)."""
    from plugins._infection_check.extensions.python.response_stream import _50_infection_analyze as ext
    from plugins._infection_check.extensions.python.response_stream_chunk import _50_infection_collect as collect

    monkeypatch.setattr(C, "get_config", lambda agent: {"prompt": "p", "mode": "thoughts"})

    async def run():
        agent = _Agent()
        agent.loop_data = type("L", (), {"iteration": 0})()
        call = _call()
        complete = json.dumps(call)
        checker = C.get_checker(agent)
        calls = []

        async def fake_run(a, snapshot):
            calls.append(snapshot)
            await asyncio.sleep(0.05)
            return "ok", "", "<ok/>"

        checker._run_check = fake_run
        await collect.InfectionCollectResponse(agent=agent).execute(stream_data={"full": complete[:-1]})
        await ext.InfectionAnalyzeThoughts(agent=agent).execute(text=complete, parsed=call)
        await asyncio.sleep(0.01)  # the background check is under way
        await checker.gate(agent, tool_name=call["tool_name"], tool_args=call["tool_args"])
        return calls

    assert len(asyncio.run(run())) == 1


def test_checker_model_calls_are_tagged():
    seen = {}

    class _Model:
        async def unified_call(self, **kwargs):
            seen["caller"] = perf.CALLER.get()
            return "<ok/>", ""

    async def run():
        checker = C.InfectionChecker(config={"prompt": "p", "history_size": 0}, iteration=0)
        agent = _Agent()
        agent.history = type("H", (), {"output": lambda self: []})()
        agent.get_utility_model = lambda: _Model()
        return await checker._run_check(agent, "snapshot")

    asyncio.run(run())
    assert seen["caller"] == "infection_check"
    assert perf.CALLER.get() == ""  # reset afterwards

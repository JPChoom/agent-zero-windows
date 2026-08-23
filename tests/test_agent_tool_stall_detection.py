"""Tests for agent.py's loop-stall circuit breaker (tool_request_stall_signature /
update_stall_tracking), used by Agent.process_tools() and by
Agent.process_llm_result_tools()'s native function_calls loop.

Motivated by a live incident: a small local model (LM Studio) got stuck
emitting the exact same malformed `{"tool_name": "code_execution_tool",
"tool_args": {}}` request 100+ times in a row for a single "hello"
message - each retry was a real, slow inference round-trip, and nothing
in the framework capped it. This adds a per-monologue counter that bails
out with a clear message once the same tool-request signature repeats
too many times in a row.

A second, initially-missed incident showed the same pathology reaching
the framework a different way: llm_result.function_calls (the native/
structured tool-call path used when a provider returns multiple tool
calls in one completion) executes every entry in that list
unconditionally via process_llm_result_tools(), with no model
round-trip - and therefore no natural pause - between them. A local
model's single degenerate completion produced hundreds of duplicate
empty-arg function calls, which the loop executed in a tight burst
(hundreds of real tool.execute() calls within a couple of seconds,
confirmed live via the log - see the second test class below).
"""

from __future__ import annotations

import pytest

from agent import (
    Agent,
    AgentConfig,
    AgentContextType,
    LoopData,
    tool_request_stall_signature,
    update_stall_tracking,
)
from helpers import history
from helpers.llm_result import LLMResult
from helpers.log import Log
from helpers.tool import Response


def test_loop_data_starts_with_no_stall_state():
    loop_data = LoopData()
    assert loop_data.stall_signature is None
    assert loop_data.stall_count == 0


def test_signature_for_misformatted_request_is_stable():
    sig1 = tool_request_stall_signature(None, "", {})
    sig2 = tool_request_stall_signature(None, "", {})
    assert sig1 == sig2 == "__misformat__"


def test_signature_differs_for_different_tools_or_args():
    sig_a = tool_request_stall_signature({}, "code_execution_tool", {})
    sig_b = tool_request_stall_signature({}, "code_execution_tool", {"code": "print(1)"})
    sig_c = tool_request_stall_signature({}, "response", {})
    assert len({sig_a, sig_b, sig_c}) == 3


def test_signature_is_stable_regardless_of_arg_key_order():
    sig1 = tool_request_stall_signature({}, "search_engine", {"a": 1, "b": 2})
    sig2 = tool_request_stall_signature({}, "search_engine", {"b": 2, "a": 1})
    assert sig1 == sig2


def test_update_stall_tracking_does_not_trip_under_the_limit():
    loop_data = LoopData()
    limit = Agent.TOOL_STALL_LIMIT
    for _ in range(limit):
        stalled = update_stall_tracking(loop_data, "same-signature", limit)
    assert stalled is False
    assert loop_data.stall_count == limit


def test_update_stall_tracking_trips_once_limit_is_exceeded():
    loop_data = LoopData()
    limit = Agent.TOOL_STALL_LIMIT
    stalled = False
    for _ in range(limit + 1):
        stalled = update_stall_tracking(loop_data, "same-signature", limit)
    assert stalled is True
    assert loop_data.stall_count == limit + 1


def test_update_stall_tracking_resets_on_a_different_signature():
    loop_data = LoopData()
    limit = Agent.TOOL_STALL_LIMIT
    # Repeat the same signature right up to (but not over) the limit...
    for _ in range(limit):
        update_stall_tracking(loop_data, "signature-a", limit)
    assert loop_data.stall_count == limit

    # ...then a genuinely different tool call (real forward progress)
    # must reset the counter rather than carrying the streak forward.
    stalled = update_stall_tracking(loop_data, "signature-b", limit)
    assert stalled is False
    assert loop_data.stall_count == 1
    assert loop_data.stall_signature == "signature-b"


def test_reproduces_the_live_incident_signature():
    """The exact malformed request observed live: code_execution_tool
    with empty args, repeated well past the limit."""
    loop_data = LoopData()
    limit = Agent.TOOL_STALL_LIMIT
    tool_request = {"tool_name": "code_execution_tool", "tool_args": {}}

    stalled = False
    for _ in range(limit + 3):
        signature = tool_request_stall_signature(
            tool_request, "code_execution_tool", {}
        )
        stalled = update_stall_tracking(loop_data, signature, limit)

    assert stalled is True


# ------------------------------------------------------------------
# process_llm_result_tools()'s native function_calls loop - the second
# call site that needed the same guard (see module docstring). Fixture
# pattern matches test_responses_architecture.py's
# test_agent_executes_native_responses_function_call_and_records_output,
# which is the established way this repo builds a minimal Agent stand-in
# via object.__new__(Agent) without running __init__.
# ------------------------------------------------------------------

class _DummyContext:
    paused = False
    log = Log()
    type = AgentContextType.USER

    def get_data(self, key, recursive=True):
        return None


class _CountingTool:
    """Always returns break_loop=False, so the caller keeps looping -
    exactly the "never makes progress" shape the breaker must catch."""

    name = "code_execution_tool"
    progress = ""

    def __init__(self, agent):
        self.agent = agent
        self.call_count = 0

    async def before_execution(self, **kwargs):
        self.args = kwargs

    async def execute(self, **kwargs):
        self.call_count += 1
        return Response(message="still running", break_loop=False)

    async def after_execution(self, response):
        self.agent.hist_add_tool_result(self.name, response.message)


def _make_dummy_agent():
    agent = object.__new__(Agent)
    agent.data = {Agent.DATA_NAME_RESPONSES_TOOL_NAME_MAP: {}}
    agent.context = _DummyContext()
    agent.config = AgentConfig(mcp_servers="")
    agent.loop_data = LoopData()
    agent.history = history.History(agent)
    agent.intervention = None
    agent.agent_name = "A0"
    agent.number = 0
    return agent


def _make_repeated_function_call_result(tool_name: str, count: int, arguments: dict | None = None):
    return LLMResult.from_response(
        {
            "id": "resp_stall_test",
            "output": [
                {
                    "type": "function_call",
                    "id": f"fc_{i}",
                    "call_id": f"call_{i}",
                    "name": tool_name,
                    "arguments": arguments or {},
                }
                for i in range(count)
            ],
        },
        provider_model_key="test/model",
    )


@pytest.mark.asyncio
async def test_function_calls_loop_stops_after_repeated_identical_calls():
    """Reproduces the second live incident: a single degenerate LLM
    completion whose function_calls list contains far more than
    TOOL_STALL_LIMIT duplicate empty-arg entries. Without the fix, the
    loop in process_llm_result_tools() executes every single one
    unconditionally; with it, execution must stop once the limit is
    exceeded instead of running hundreds of real tool calls in a burst."""
    agent = _make_dummy_agent()
    tool = _CountingTool(agent)
    agent.get_tool = lambda **kwargs: tool

    limit = Agent.TOOL_STALL_LIMIT
    result = _make_repeated_function_call_result("code_execution_tool", count=limit + 20)

    outcome = await Agent.process_llm_result_tools(agent, result)

    assert outcome is not None
    assert "code_execution_tool" in outcome
    # Executed up to (limit + 1) times - the extra call is the one whose
    # *result* trips the breaker before it can execute the (limit + 2)th.
    assert tool.call_count <= limit + 1
    assert tool.call_count < limit + 20


@pytest.mark.asyncio
async def test_function_calls_loop_does_not_trip_for_varied_calls():
    """A model legitimately calling the same tool many times with
    different args each time (normal multi-step work) must not be
    mistaken for a stall."""
    agent = _make_dummy_agent()
    tool = _CountingTool(agent)
    agent.get_tool = lambda **kwargs: tool

    limit = Agent.TOOL_STALL_LIMIT
    call_count = limit + 5
    result = LLMResult.from_response(
        {
            "id": "resp_varied_test",
            "output": [
                {
                    "type": "function_call",
                    "id": f"fc_{i}",
                    "call_id": f"call_{i}",
                    "name": "code_execution_tool",
                    "arguments": {"step": i},
                }
                for i in range(call_count)
            ],
        },
        provider_model_key="test/model",
    )

    outcome = await Agent.process_llm_result_tools(agent, result)

    assert outcome is None
    assert tool.call_count == call_count


# ------------------------------------------------------------------
# monologue()'s repeated-identical-response branch - the third call
# site. That branch (agent.py, `if self.loop_data.last_response ==
# agent_response`) only appends a warning and loops; it never reaches
# process_tools()/process_llm_result_tools(), so neither of those
# guards can see it. Observed live: a 27B local model regenerated the
# same response over and over, producing megabytes of output and zero
# tool calls, with nothing capping the cycle.
# ------------------------------------------------------------------

REPEAT_SIGNATURE = "__repeat_response__"


def test_repeated_identical_response_trips_after_the_limit():
    loop_data = LoopData()
    limit = Agent.TOOL_STALL_LIMIT

    stalled = False
    for _ in range(limit + 1):
        stalled = update_stall_tracking(loop_data, REPEAT_SIGNATURE, limit)

    assert stalled is True
    assert loop_data.stall_count == limit + 1


def test_repeated_identical_response_does_not_trip_under_the_limit():
    loop_data = LoopData()
    limit = Agent.TOOL_STALL_LIMIT

    stalled = False
    for _ in range(limit):
        stalled = update_stall_tracking(loop_data, REPEAT_SIGNATURE, limit)

    assert stalled is False


def test_repeat_signature_is_distinct_from_tool_call_signatures():
    """The repeat branch and the tool-call branches share one counter,
    so their signatures must not collide - otherwise a model alternating
    between "repeated a response" and "made a real tool call" would
    accumulate toward the limit instead of resetting."""
    tool_sig = tool_request_stall_signature({}, "code_execution_tool", {})
    misformat_sig = tool_request_stall_signature(None, "", {})

    assert REPEAT_SIGNATURE != tool_sig
    assert REPEAT_SIGNATURE != misformat_sig


def test_alternating_repeat_and_tool_calls_resets_the_counter():
    """Real forward progress between repeats must reset the streak."""
    loop_data = LoopData()
    limit = Agent.TOOL_STALL_LIMIT
    tool_sig = tool_request_stall_signature({}, "code_execution_tool", {"step": 1})

    stalled = False
    for _ in range(limit * 3):
        stalled = update_stall_tracking(loop_data, REPEAT_SIGNATURE, limit)
        assert stalled is False
        stalled = update_stall_tracking(loop_data, tool_sig, limit)
        assert stalled is False

    assert loop_data.stall_count == 1


def test_emit_stall_warning_accepts_the_repeat_prompt_file():
    """The repeat branch uses its own prompt (the tool-request wording
    doesn't fit), so _emit_stall_warning must honor prompt_file."""
    agent = _make_dummy_agent()
    agent.loop_data.stall_count = Agent.TOOL_STALL_LIMIT + 1

    message = Agent._emit_stall_warning(
        agent, "", prompt_file="fw.msg_stalled_repeat.md"
    )

    assert "same response" in message
    assert str(Agent.TOOL_STALL_LIMIT + 1) in message

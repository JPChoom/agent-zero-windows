"""Tests for agent.py's loop-stall circuit breaker (tool_request_stall_signature /
update_stall_tracking), used by Agent.process_tools().

Motivated by a live incident: a small local model (LM Studio) got stuck
emitting the exact same malformed `{"tool_name": "code_execution_tool",
"tool_args": {}}` request 100+ times in a row for a single "hello"
message - each retry was a real, slow inference round-trip, and nothing
in the framework capped it. This adds a per-monologue counter that bails
out with a clear message once the same tool-request signature repeats
too many times in a row.
"""

from __future__ import annotations

from agent import (
    Agent,
    LoopData,
    tool_request_stall_signature,
    update_stall_tracking,
)


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

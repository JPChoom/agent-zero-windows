"""Tests for tools/response.py's ResponseTool.execute().

Guards against a real crash seen live: a local/weaker model can emit a
`response` tool call whose args are missing both "text" and "message"
(malformed tool-call JSON) - the original code did a raw
self.args["message"] with no fallback, which raised KeyError and crashed
the whole turn (see agent.py's handle_exception traceback). Fixed to fall
back to "" instead.
"""

from __future__ import annotations

import pytest

from tools.response import ResponseTool


def _make_tool(args: dict) -> ResponseTool:
    return ResponseTool(
        agent=None,  # type: ignore[arg-type]
        name="response",
        method=None,
        args=args,
        message="",
        loop_data=None,
    )


@pytest.mark.asyncio
async def test_response_tool_prefers_text_over_message():
    tool = _make_tool({"text": "hello", "message": "ignored"})
    response = await tool.execute()
    assert response.message == "hello"
    assert response.break_loop is True


@pytest.mark.asyncio
async def test_response_tool_uses_empty_text_when_key_present():
    # "text" present with an empty value must still win over "message" -
    # matches the original "text" in self.args semantics.
    tool = _make_tool({"text": "", "message": "fallback"})
    response = await tool.execute()
    assert response.message == ""


@pytest.mark.asyncio
async def test_response_tool_falls_back_to_message_when_no_text():
    tool = _make_tool({"message": "hi there"})
    response = await tool.execute()
    assert response.message == "hi there"


@pytest.mark.asyncio
async def test_response_tool_does_not_crash_when_both_keys_missing():
    tool = _make_tool({})
    response = await tool.execute()
    assert response.message == ""
    assert response.break_loop is True

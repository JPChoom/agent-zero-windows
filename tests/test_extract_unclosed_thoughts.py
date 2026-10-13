from helpers import extract_tools

UNCLOSED = (
    '{"thoughts": ["Done.", "headline": "Cleanup", "tool_name": "response", '
    '"tool_args": {"text": "ok"}}'
)
CLOSED = (
    '{"thoughts": ["Done."], "headline": "Cleanup", "tool_name": "response", '
    '"tool_args": {"text": "ok"}}'
)


def test_unclosed_thoughts_array_is_repaired():
    request = extract_tools.extract_tool_request(UNCLOSED)
    assert request is not None
    assert request["tool_name"] == "response"
    assert request["thoughts"] == ["Done."]
    assert request["tool_args"] == {"text": "ok"}


def test_well_formed_request_is_untouched():
    assert extract_tools.extract_tool_request(CLOSED)["thoughts"] == ["Done."]


def test_unrelated_garbage_stays_unparseable():
    assert extract_tools.extract_tool_request('{"thoughts": ["a", "b"]}') is None

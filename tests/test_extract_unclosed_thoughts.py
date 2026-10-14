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


CALL = '{"thoughts": ["t"], "headline": "h", "tool_name": "response", "tool_args": {"text": "ok"}}'


def test_prose_before_a_trailing_tool_call_is_accepted():
    request = extract_tools.extract_tool_request("Retrying the read:\n\n" + CALL)
    assert request is not None and request["tool_name"] == "response"


def test_tool_call_followed_by_text_is_not_executed():
    assert extract_tools.extract_tool_request(CALL + "\n\nThat is my plan.") is None


def test_two_competing_calls_are_not_executed():
    assert extract_tools.extract_tool_request("First " + CALL + " then " + CALL) is None

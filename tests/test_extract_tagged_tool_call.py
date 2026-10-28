"""Tool calls wrapped in a model's native tool-call tags.

Qwen-style models drift into their own wrapper (<tool_call> ... </tool_call>,
seen live also as </tool> and </invoke>) and then often drop the last brace
of the JSON. Every one of those replies was rejected as misformatted, the
model resent it unchanged, and the turn ended after six tries.
"""

from helpers import extract_tools

ARGS = '{"runtime": "terminal", "session": 3, "reset": true, "code": "Get-ChildItem C:\\\\work; Write-Output \'done\'"}'
CALL = '{"tool_name": "code_execution_tool", "tool_args": ' + ARGS + "}"
CODE = "Get-ChildItem C:\\work; Write-Output 'done'"


def _code(reply):
    request = extract_tools.extract_tool_request(reply)
    assert request is not None, reply
    assert request["tool_name"] == "code_execution_tool"
    return request["tool_args"]["code"]


def test_one_brace_short_with_closing_tags_is_repaired():
    # the shape seen live: '...'"}\n</tool>\n</invoke>'
    assert _code("<tool_call>\n" + CALL[:-1] + "\n</tool>\n</invoke>") == CODE
    assert _code("<tool_call>\n" + CALL[:-1] + "\n</tool>") == CODE


def test_complete_call_in_tags_is_accepted():
    assert _code("<tool_call>\n" + CALL + "\n</tool_call>") == CODE


def test_announcing_sentence_before_the_tags_is_kept_allowed():
    assert _code("The path was wrong. Building it again.\n\n<tool_call>\n" + CALL[:-1] + "\n</tool>") == CODE


def test_escaped_final_quote_is_repaired():
    broken = CALL[:-3] + '\\"}}'  # ...'done'\"}} : the string never closed
    assert _code("<tool_call>\n" + broken + "\n</tool_call>") == CODE


def test_a_call_still_streaming_is_never_completed():
    # no closing tag yet: the model may still be writing arguments
    for cut in range(1, len(CALL)):
        assert extract_tools.extract_tool_request("<tool_call>\n" + CALL[:cut]) is None


def test_a_call_cut_inside_a_string_is_not_completed():
    cut = CALL.index("Write-Output")
    assert extract_tools.extract_tool_request("<tool_call>\n" + CALL[:cut] + "\n</tool_call>") is None


def test_tags_inside_an_argument_are_left_alone():
    call = CALL.replace("Get-ChildItem", "Write-Output '<tool>x</tool>';")
    request = extract_tools.extract_tool_request("<tool_call>\n" + call + "\n</tool_call>")
    assert request["tool_args"]["code"].startswith("Write-Output '<tool>x</tool>';")


def test_text_after_the_call_still_rejects_it():
    assert extract_tools.extract_tool_request("<tool_call>\n" + CALL + "\n</tool_call>\nAnd then I will...") is None


def test_two_calls_in_tags_are_not_executed():
    assert extract_tools.extract_tool_request(CALL + "\n<tool_call>\n" + CALL + "\n</tool_call>") is None


def test_not_a_tool_request_stays_unparseable():
    assert extract_tools.extract_tool_request('<tool_call>\n{"name": "x", "value": 1\n</tool_call>') is None

"""LogFromStream must not crash on a partial mid-stream JSON parse.

Observed live: a real turn hit
"TypeError: argument of type 'NoneType' is not iterable" from
"if 'tool_args' in parsed and 'runtime' in parsed['tool_args']:" -
tool_name streams in as "code_execution_tool" before tool_args' value has
arrived, so tool_args is present as a key but still None, not absent.
The extension-isolation default (helpers/extension.py) caught this and
logged a warning instead of aborting the turn, but the underlying bug -
this extension crashing on a normal, expected streaming state - is worth
fixing directly rather than just relying on isolation to paper over it
every time.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from extensions.python.response_stream._10_log_from_stream import LogFromStream


class _LogItem:
    def __init__(self):
        self.kvps = None
        self.updates = []

    def update(self, **kw):
        self.updates.append(kw)
        self.kvps = kw.get("kvps", self.kvps)


class _Log:
    def __init__(self):
        self.item = _LogItem()

    def log(self, **kw):
        return self.item


class _Context:
    def __init__(self):
        self.log = _Log()


class _Agent:
    agent_name = "A0"

    def __init__(self):
        self.context = _Context()

    def read_prompt(self, name, **k):
        return "PROMPT"


class _LoopData:
    def __init__(self):
        self.params_temporary = {}


@pytest.mark.asyncio
async def test_tool_args_present_but_none_does_not_raise():
    """The exact regression: tool_name has streamed in, tool_args key
    exists but its value hasn't arrived yet."""
    agent = _Agent()
    ext = LogFromStream(agent=agent)  # type: ignore[arg-type]

    parsed = {"tool_name": "code_execution_tool", "tool_args": None}

    # Must not raise.
    await ext.execute(loop_data=_LoopData(), text="...", parsed=parsed)

    assert agent.context.log.item.kvps["step"] == "Using code_execution_tool..."


@pytest.mark.asyncio
async def test_tool_args_missing_entirely_does_not_raise():
    agent = _Agent()
    ext = LogFromStream(agent=agent)  # type: ignore[arg-type]

    parsed = {"tool_name": "code_execution_tool"}

    await ext.execute(loop_data=_LoopData(), text="...", parsed=parsed)

    assert agent.context.log.item.kvps["step"] == "Using code_execution_tool..."


@pytest.mark.asyncio
async def test_a_complete_tool_args_still_produces_the_detailed_step_label():
    """The guard must only catch the partial state, not change behavior
    once tool_args has actually arrived."""
    agent = _Agent()
    ext = LogFromStream(agent=agent)  # type: ignore[arg-type]

    parsed = {
        "tool_name": "code_execution_tool",
        "tool_args": {"runtime": "python", "code": "print(1)"},
    }

    await ext.execute(loop_data=_LoopData(), text="...", parsed=parsed)

    assert "Writing Python code" in agent.context.log.item.kvps["step"]


@pytest.mark.asyncio
async def test_a_non_dict_tool_args_does_not_raise():
    """Belt and suspenders: any non-dict value in this position (a
    partially-streamed string, a list) must be tolerated the same way."""
    agent = _Agent()
    ext = LogFromStream(agent=agent)  # type: ignore[arg-type]

    parsed = {"tool_name": "code_execution_tool", "tool_args": "still streaming"}

    await ext.execute(loop_data=_LoopData(), text="...", parsed=parsed)

    assert agent.context.log.item.kvps["step"] == "Using code_execution_tool..."

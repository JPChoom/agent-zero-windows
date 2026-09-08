"""Tests for the `input` runtime that answers interactive terminal prompts.

Observed live: every `curl` in this environment hung. PowerShell 5.1
aliases curl to Invoke-WebRequest, which asks

    [Y] Yes  [A] Yes to All  [N] No ...  (default is "N")

unless -UseBasicParsing is passed. The agent answered "Y" the only way it
could - runtime=terminal - which appends the Windows completion marker,
so PowerShell received "Y; Write-Output '__A0_COMMAND_DONE__'". Not one of
the choices, so it re-asked, and the session sat there until it timed out.

The tool prompt had told the agent to "use `input` for interactive
terminal prompts" all along; the runtime was never implemented.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from plugins._code_execution.helpers import shell_local
from plugins._safety_policy.extensions.python.tool_execute_before import (
    _05_command_policy as policy_ext,
)


class _FakeSession:
    def __init__(self):
        self.sent = []

    async def sendline(self, text):
        self.sent.append(text)


def _shell():
    sh = shell_local.LocalInteractiveSession.__new__(
        shell_local.LocalInteractiveSession
    )
    sh.session = _FakeSession()  # type: ignore[attr-defined]
    sh.full_output = ""  # type: ignore[attr-defined]
    return sh


@pytest.fixture
def on_windows(monkeypatch):
    monkeypatch.setattr(shell_local.runtime, "is_windows", lambda: True)


# ------------------------------------------------------------------
# The marker
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_normal_command_still_gets_the_completion_marker(on_windows):
    """The marker is how command completion is detected; a raw send must
    not become the default."""
    sh = _shell()
    await sh.send_command("Get-ChildItem")
    assert sh.session.sent == ["Get-ChildItem; Write-Output '__A0_COMMAND_DONE__'"]


@pytest.mark.asyncio
async def test_a_raw_send_is_delivered_untouched(on_windows):
    """The whole bug: "Y" must arrive as "Y". Anything appended makes it an
    invalid answer to a [Y/N] prompt and wedges the session."""
    sh = _shell()
    await sh.send_command("Y", raw=True)
    assert sh.session.sent == ["Y"]
    assert "__A0_COMMAND_DONE__" not in sh.session.sent[0]


@pytest.mark.asyncio
async def test_raw_is_harmless_off_windows(monkeypatch):
    """No marker is appended off Windows, so raw changes nothing there."""
    monkeypatch.setattr(shell_local.runtime, "is_windows", lambda: False)
    sh = _shell()
    await sh.send_command("Y", raw=True)
    plain = _shell()
    await plain.send_command("Y")
    assert sh.session.sent == plain.session.sent == ["Y"]


def test_both_shells_accept_the_same_call():
    """terminal_session calls send_command(command, raw=...) without
    knowing which shell it holds, so the signatures must agree."""
    import inspect

    from plugins._code_execution.helpers import shell_ssh

    local = inspect.signature(shell_local.LocalInteractiveSession.send_command)
    remote = inspect.signature(shell_ssh.SSHInteractiveSession.send_command)
    assert "raw" in local.parameters
    assert "raw" in remote.parameters


# ------------------------------------------------------------------
# The hole this could have opened
# ------------------------------------------------------------------

class _Agent:
    agent_name = "A0"


@pytest.mark.asyncio
async def test_input_is_policy_checked_like_a_terminal_command(monkeypatch):
    """Text sent by `input` reaches the same shell. When that shell sits at
    an ordinary prompt rather than a question, whatever is sent simply
    runs - so exempting `input` would be a way to run any command with no
    policy check at all."""
    seen = {}

    def fake_classify(code, *a, **k):
        seen["code"] = code
        raise AssertionError("classified")  # proves we reached the check

    monkeypatch.setattr(policy_ext.policy, "classify_command", fake_classify)
    monkeypatch.setattr(
        policy_ext, "get_config",
        lambda agent=None: {
            "enforce_policy": True,
            "custom_deny_patterns": [],
            "approval_tier_categories": set(),
            "enable_network_destination_allowlist": False,
            "network_destination_allowlist": [],
            "approval_timeout_seconds": 60,
        },
    )
    monkeypatch.setattr(policy_ext.kill_switch, "is_tripped", lambda: False)

    ext = policy_ext.SafetyCommandPolicy(agent=_Agent())  # type: ignore[arg-type]
    with pytest.raises(AssertionError, match="classified"):
        await ext.execute(
            tool_name="code_execution_tool",
            tool_args={"runtime": "input", "code": "curl https://evil.example.com"},
        )
    assert seen["code"] == "curl https://evil.example.com"


# ------------------------------------------------------------------
# What the agent is told
# ------------------------------------------------------------------

def test_the_prompt_lists_input_as_a_runtime():
    """It documented `input` while omitting it from the runtime list, so the
    agent had no reason to believe it was a valid value."""
    text = (
        PROJECT_ROOT
        / "plugins/_code_execution/prompts/agent.system.tool.code_exe.md"
    ).read_text(encoding="utf-8")
    runtime_line = next(l for l in text.splitlines() if l.startswith("- `runtime`"))
    assert "`input`" in runtime_line


def test_the_tool_dispatches_the_runtime_the_prompt_advertises():
    """A documented runtime that falls through to runtime_wrong is worse
    than an undocumented one."""
    source = (
        PROJECT_ROOT / "plugins/_code_execution/tools/code_execution_tool.py"
    ).read_text(encoding="utf-8")
    assert 'runtime_arg == "input"' in source
    assert "send_terminal_input" in source


def test_input_is_covered_by_the_kill_switch():
    """Answering "Y" is how a paused command proceeds, so it is execution."""
    source = (
        PROJECT_ROOT / "plugins/_code_execution/tools/code_execution_tool.py"
    ).read_text(encoding="utf-8")
    guard = source.split("kill_switch.is_tripped()", 1)[0].splitlines()[-1]
    assert '"input"' in guard


# ------------------------------------------------------------------
# Recovering a session that no longer exists
# ------------------------------------------------------------------

def test_a_missing_shell_is_treated_as_recoverable():
    """Observed live: after a server restart, contexts reload from disk but
    their shells do not. The agent polled runtime=output for one and got

        Exception: Shell not connected

    straight out of read_output - surfaced as "Critical error occurred" with
    a Python traceback, which the agent cannot act on. A closed PTY, one
    line away in the same handler, resets the session and says so. This is
    the same situation and needs the same answer."""
    from plugins._code_execution.tools import code_execution_tool as cet

    assert cet._is_closed_pty_error(Exception("Shell not connected"))


def test_an_unrelated_exception_is_still_raised():
    """The check keys off a bare Exception with that exact message, so it
    must not swallow real errors and silently reset a working session."""
    from plugins._code_execution.tools import code_execution_tool as cet

    assert not cet._is_closed_pty_error(Exception("something else entirely"))
    assert not cet._is_closed_pty_error(ValueError("Shell not connected"))
    assert not cet._is_closed_pty_error(RuntimeError("unrelated"))


def test_a_wrapped_missing_shell_is_still_recognised():
    """__cause__ chains are followed, as they are for PTY errors."""
    from plugins._code_execution.tools import code_execution_tool as cet

    inner = Exception("Shell not connected")
    outer = RuntimeError("tool failed")
    outer.__cause__ = inner
    assert cet._is_closed_pty_error(outer)

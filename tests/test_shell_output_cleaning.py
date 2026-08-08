"""Regression tests for garbled terminal transcripts on Windows.

Live testing surfaced two issues in captured code_execution_tool output:

1. OSC escape sequences (window-title / progress-state reporting, e.g. the
   ConEmu-style "9;4;..." progress codes PowerShell 7+ / Windows Terminal
   emit during long operations like `dotnet build`) leaked through as
   literal text. shell_ssh.clean_string()'s ANSI-stripping regex's "Fe
   escape" branch matched a bare "ESC ]" (']' falls in its \\-_ range) and
   stopped there, leaving the OSC payload and BEL/ST terminator behind.

2. PowerShell's PSReadLine module redraws the input line with cursor-
   repositioning escapes as it applies syntax highlighting. Since there's
   no real terminal emulation here (escape codes are stripped, not
   interpreted), each redraw's fragment just concatenated onto the last,
   producing a growing "d, do, dot, dotn..." echo of the command being
   typed. PSReadLine is disabled for local Windows sessions to fix this at
   the source instead of trying to collapse the redraws after the fact.

3. Removing PSReadLine needs real wall-clock settle time that isn't
   reflected in the terminal's own output at all: a command written too
   soon after (even once a fresh prompt has visibly reappeared) can be
   silently dropped and never reach PowerShell - confirmed empirically
   against raw winpty I/O by bisecting the delay (1s: consistently fails,
   1.5s+: consistently safe). connect() sleeps through a safety window
   before treating the session as ready for the caller's first command.
"""

import asyncio

import pytest

from plugins._code_execution.helpers import shell_local
from plugins._code_execution.helpers.shell_ssh import clean_string


# ------------------------------------------------------------------
# clean_string: OSC sequence stripping
# ------------------------------------------------------------------

def test_clean_string_strips_bel_terminated_osc_sequence():
    raw = "\x1b]9;4;3;\x07dotnet build\x1b]9;4;0;0;C:\\WINDOWS\\powershell.exe\x07done"

    result = clean_string(raw)

    assert "9;4" not in result
    assert "powershell.exe" not in result
    assert "dotnet build" in result
    assert "done" in result


def test_clean_string_strips_st_terminated_osc_sequence():
    raw = "\x1b]0;My Window Title\x1b\\hello"

    result = clean_string(raw)

    assert "My Window Title" not in result
    assert result == "hello"


def test_clean_string_still_strips_csi_color_codes():
    raw = "\x1b[31mred text\x1b[0m normal"

    result = clean_string(raw)

    assert result == "red text normal"


def test_clean_string_handles_osc_and_csi_together():
    raw = "\x1b]9;4;1;50\x07\x1b[32mBuilding...\x1b[0m\x1b]9;4;0;0;\x07"

    result = clean_string(raw)

    assert "9;4" not in result
    assert result == "Building..."


def test_clean_string_still_collapses_carriage_return_redraws():
    """Pre-existing behavior (not part of this fix) must still work: a
    single-line \\r-based redraw collapses to its final state."""
    raw = "a\rab\rabc\rabc done\n"

    result = clean_string(raw)

    assert result == "abc done\n"


# ------------------------------------------------------------------
# LocalInteractiveSession.connect(): PSReadLine removal on Windows
# ------------------------------------------------------------------

class _FakeSession:
    def __init__(self):
        self.sent_lines: list[str] = []

    async def start(self):
        pass

    async def sendline(self, line: str):
        self.sent_lines.append(line)

    async def read_full_until_idle(self, idle_timeout, total_timeout):
        return ""


@pytest.mark.asyncio
async def test_connect_removes_psreadline_on_windows(monkeypatch):
    from plugins._code_execution.helpers import tty_session

    monkeypatch.setattr(shell_local.runtime, "is_windows", lambda: True)
    monkeypatch.setattr(shell_local.runtime, "get_terminal_executable", lambda: "powershell.exe")

    fake_session = _FakeSession()
    monkeypatch.setattr(tty_session, "TTYSession", lambda *a, **k: fake_session)

    session = shell_local.LocalInteractiveSession()
    await session.connect()

    assert any("PSReadLine" in line for line in fake_session.sent_lines)


@pytest.mark.asyncio
async def test_connect_does_not_touch_psreadline_off_windows(monkeypatch):
    from plugins._code_execution.helpers import tty_session

    monkeypatch.setattr(shell_local.runtime, "is_windows", lambda: False)
    monkeypatch.setattr(shell_local.runtime, "get_terminal_executable", lambda: "/bin/bash")

    fake_session = _FakeSession()
    monkeypatch.setattr(tty_session, "TTYSession", lambda *a, **k: fake_session)

    session = shell_local.LocalInteractiveSession()
    await session.connect()

    assert fake_session.sent_lines == []


@pytest.mark.asyncio
async def test_connect_waits_out_psreadline_settle_window_on_windows(monkeypatch):
    """PSReadLine's removal needs real wall-clock settle time that isn't
    reflected in the terminal's own output stream at all: a command written
    too soon after (even once a fresh prompt has visibly reappeared) can be
    silently dropped and never reach PowerShell. Confirmed empirically
    against raw winpty I/O - 1s is unreliable, 1.5s+ is consistently safe.
    connect() must sleep through a safety window before treating the
    session as ready for the caller's first real command."""
    from plugins._code_execution.helpers import tty_session

    monkeypatch.setattr(shell_local.runtime, "is_windows", lambda: True)
    monkeypatch.setattr(shell_local.runtime, "get_terminal_executable", lambda: "powershell.exe")

    fake_session = _FakeSession()
    monkeypatch.setattr(tty_session, "TTYSession", lambda *a, **k: fake_session)

    sleep_calls: list[float] = []
    real_sleep = asyncio.sleep

    async def _fake_sleep(seconds):
        sleep_calls.append(seconds)
        await real_sleep(0)  # yield control without actually waiting

    monkeypatch.setattr(shell_local.asyncio, "sleep", _fake_sleep)

    session = shell_local.LocalInteractiveSession()
    await session.connect()

    assert sleep_calls, "connect() must sleep after removing PSReadLine"
    assert sleep_calls[0] >= 1.5


@pytest.mark.asyncio
async def test_connect_does_not_sleep_off_windows(monkeypatch):
    from plugins._code_execution.helpers import tty_session

    monkeypatch.setattr(shell_local.runtime, "is_windows", lambda: False)
    monkeypatch.setattr(shell_local.runtime, "get_terminal_executable", lambda: "/bin/bash")

    fake_session = _FakeSession()
    monkeypatch.setattr(tty_session, "TTYSession", lambda *a, **k: fake_session)

    sleep_calls: list[float] = []
    real_sleep = asyncio.sleep

    async def _fake_sleep(seconds):
        sleep_calls.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(shell_local.asyncio, "sleep", _fake_sleep)

    session = shell_local.LocalInteractiveSession()
    await session.connect()

    assert sleep_calls == []

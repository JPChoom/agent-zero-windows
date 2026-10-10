import asyncio
import os
import platform
import select
import subprocess
import time
import sys
from typing import Optional, Tuple
from helpers import runtime
from plugins._code_execution.helpers import tty_session
from plugins._code_execution.helpers.shell_ssh import clean_string


def disable_pagers_in_env(env: dict | None = None) -> dict:
    """Return a copy of ``env`` with terminal pagers disabled.

    Commands such as ``git diff``/``git log`` detect a TTY and pipe their output
    through a pager (``more``/``less``). The non-interactive shells created by
    the code execution tool never receive any user input, so the pager blocks
    forever and spins at 100% CPU per process. Pointing the pager variables at
    ``cat`` lets the output stream through instead. See issue #1697.
    """
    env = dict(env if env is not None else os.environ)
    env["PAGER"] = "cat"
    env["GIT_PAGER"] = "cat"
    return env


class LocalInteractiveSession:
    def __init__(self, cwd: str|None = None):
        self.session: tty_session.TTYSession|None = None
        self.full_output = ''
        self.cwd = cwd

    def kill(self):
        """End the shell now (synchronous; used for deterministic cleanup)."""
        if self.session:
            self.session.kill()

    def __del__(self):
        try:
            self.kill()
        except Exception:
            pass

    async def connect(self):
        self.session = tty_session.TTYSession(
            runtime.get_terminal_executable(),
            cwd=self.cwd,
            env=disable_pagers_in_env(),
        )
        await self.session.start()
        if runtime.is_windows():
            # PSReadLine (PowerShell's interactive line editor) redraws the
            # input buffer with cursor-repositioning escape sequences as it
            # applies syntax highlighting. Those redraws get stripped as
            # generic ANSI codes without being interpreted (no real terminal
            # emulation here), so each redraw's fragment just concatenates
            # onto the last - producing a noisy, growing "d, do, dot,
            # dotn..." echo in captured output. Commands here always arrive
            # as complete strings, never typed interactively, so PSReadLine
            # has no upside for this session; removing it drops PowerShell
            # back to its simpler legacy line input, whose output our
            # cleanup already handles correctly.
            await self.session.sendline(
                "Remove-Module -Name PSReadLine -ErrorAction SilentlyContinue"
            )
            # PSReadLine's removal needs real wall-clock settle time that
            # isn't reflected in the terminal's visible output at all: a
            # command written too soon after (even once the new prompt has
            # already reappeared on screen) can be silently dropped and
            # never reach PowerShell. Confirmed empirically against raw
            # winpty I/O - 1s is unreliable, 1.5s+ is consistently safe.
            await asyncio.sleep(2.5)
        await self.session.read_full_until_idle(idle_timeout=1, total_timeout=1)

    async def close(self):
        if self.session:
            session = self.session
            self.session = None
            try:
                await session.close()
            except Exception:
                try:
                    session.kill()
                except Exception:
                    pass

    async def send_command(self, command: str, raw: bool = False):
        if not self.session:
            raise Exception("Shell not connected")
        self.full_output = ""
        # Native Windows PowerShell completion marker.
        # Allows Agent Zero to detect deterministic command completion.
        #
        # raw=True skips it, for text typed at an interactive prompt rather
        # than run as a command. Appending the marker to an answer corrupts
        # it: PowerShell asking "[Y] Yes [N] No" receives
        # "Y; Write-Output '...'", which is not one of the choices, so the
        # prompt re-asks and the session wedges until it times out. Observed
        # on every `curl` here, which PowerShell 5.1 aliases to
        # Invoke-WebRequest and guards with exactly such a prompt.
        if runtime.is_windows() and not raw:
            command = f"{command}; Write-Output '__A0_COMMAND_DONE__'"

        await self.session.sendline(command)

    def is_terminated(self) -> bool:
        return self.session is None or self.session.is_terminated()

    def get_exit_code(self) -> int | None:
        if not self.session:
            return None
        return self.session.get_exit_code()

    async def read_output(self, timeout: float = 0, reset_full_output: bool = False) -> Tuple[str, Optional[str]]:
        if not self.session:
            raise Exception("Shell not connected")

        if reset_full_output:
            self.full_output = ""

        # get output from terminal
        partial_output = await self.session.read_full_until_idle(idle_timeout=0.01, total_timeout=timeout)
        self.full_output += partial_output

        # clean output
        partial_output = clean_string(partial_output)
        clean_full_output = clean_string(self.full_output)

        if not partial_output:
            return clean_full_output, None
        return clean_full_output, partial_output

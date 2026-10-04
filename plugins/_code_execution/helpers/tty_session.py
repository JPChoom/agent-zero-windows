import asyncio, os, sys, platform, errno, signal, threading, time

_IS_WIN = platform.system() == "Windows"
if _IS_WIN:
    import winpty  # pip install pywinpty # type: ignore
    import msvcrt

_CLOSE_TIMEOUT_SECONDS = 2
# signal.SIGKILL does not exist on Windows. Referencing it there raised
# AttributeError, which _signal_process's own except blocks swallowed - so
# kill() silently never killed anything and close()'s force-kill fallback
# raised instead. 9 is SIGKILL's value on every POSIX platform.
_SIGKILL = getattr(signal, "SIGKILL", 9)


def _reconfigure_stream_errors(stream) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if not callable(reconfigure):
        return
    reconfigure(errors="replace")


#  Make stdin / stdout tolerant to broken UTF-8 so input() never aborts
_reconfigure_stream_errors(sys.stdin)
_reconfigure_stream_errors(sys.stdout)


# ──────────────────────────── PUBLIC CLASS ────────────────────────────


class TTYSession:
    def __init__(self, cmd, *, cwd=None, env=None, encoding="utf-8", echo=False):
        self.cmd = cmd if isinstance(cmd, str) else " ".join(cmd)
        self.cwd = cwd
        self.env = env or os.environ.copy()
        self.encoding = encoding
        self.echo = echo  # ← store preference
        self._proc = None
        self._buf: asyncio.Queue = None  # type: ignore
        self._pump_task = None
        self._pty_master = None
        self._pty_master_ref = None

    def __del__(self):
        # Must stay synchronous and must never drive an event loop. __del__
        # runs wherever garbage collection happens to fire - including in the
        # middle of a task step on the running loop. This used to be
        # asyncio.run(self.close()) under nest_asyncio, which spun a nested
        # loop right there; when the interrupted task had just scheduled a
        # timer (tty_session drain()'s 10ms sleep) and close() outlasted it,
        # the nested loop ran that task's own wakeup while its context was
        # still entered ("cannot enter context: ... is already entered"),
        # the wakeup was dropped, and the agent froze permanently mid-turn
        # with no model activity (observed live after a terminal reset).
        # Killing the process is enough: the reader sees EOF and the pump
        # task finishes on its own. Graceful shutdown belongs to callers
        # that await close().
        try:
            self.kill()
        except Exception:
            pass

    # ── user-facing coroutines ────────────────────────────────────────
    async def start(self):
        self._buf = asyncio.Queue()
        if _IS_WIN:
            self._proc = await _spawn_winpty(
                self.cmd, self.cwd, self.env, self.echo
            )  # ← pass echo
        else:
            self._proc = await _spawn_posix_pty(
                self.cmd, self.cwd, self.env, self.echo
            )  # ← pass echo
            self._pty_master_ref = getattr(self._proc, "_pty_master_ref", None)
            self._pty_master = (
                self._pty_master_ref.get("fd")
                if self._pty_master_ref is not None
                else getattr(self._proc, "_pty_master", None)
            )
        self._pump_task = asyncio.create_task(self._pump_stdout())

    async def close(self):
        # Cancel the pump task if it exists
        if self._pump_task:
            self._pump_task.cancel()
            try:
                await self._pump_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        # Terminate the process if it exists
        if self._proc:
            if getattr(self._proc, "returncode", None) is None:
                self._signal_process(signal.SIGTERM)
            try:
                await asyncio.wait_for(self._proc.wait(), _CLOSE_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                self._signal_process(_SIGKILL)
                try:
                    await asyncio.wait_for(self._proc.wait(), _CLOSE_TIMEOUT_SECONDS)
                except Exception:
                    pass
            except Exception:
                pass

        self._release_pty_master()
        self._proc = None
        self._pump_task = None

    def _signal_process(self, sig):
        if self._proc is None:
            return
        try:
            if _IS_WIN:
                if sig == _SIGKILL:
                    self._proc.kill()
                else:
                    self._proc.terminate()
                return
            os.killpg(self._proc.pid, sig)
        except ProcessLookupError:
            pass
        except Exception:
            try:
                if sig == _SIGKILL:
                    self._proc.kill()
                else:
                    self._proc.terminate()
            except Exception:
                pass

    def _release_pty_master(self):
        """Release the POSIX PTY master exactly once.

        The fd number is invalidated before os.close() so that a concurrent or
        later cleanup path cannot close the same integer after the OS has reused
        it for another file/socket.
        """
        ref = self._pty_master_ref
        master = ref.get("fd") if ref is not None else self._pty_master
        if master is None:
            self._pty_master = None
            return
        if ref is not None:
            ref["fd"] = None
        self._pty_master = None
        try:
            loop = asyncio.get_running_loop()
            loop.remove_reader(master)
        except Exception:
            pass
        try:
            os.close(master)
        except OSError:
            pass
        self._pty_master_ref = None

    async def send(self, data: str | bytes):
        if self._proc is None:
            raise RuntimeError("TTYSpawn is not started")
        if not _IS_WIN:
            master = (
                self._pty_master_ref.get("fd")
                if self._pty_master_ref is not None
                else self._pty_master
            )
            if master is None:
                raise RuntimeError("TTYSpawn PTY is closed")
        if getattr(self._proc, "returncode", None) is not None:
            raise RuntimeError("TTYSpawn process has exited")
        if isinstance(data, str):
            data = data.encode(self.encoding)
        try:
            self._proc.stdin.write(data)  # type: ignore
            await self._proc.stdin.drain()  # type: ignore
        except OSError as e:
            if e.errno in (errno.EBADF, errno.EIO, errno.EINVAL):
                self._release_pty_master()
                raise RuntimeError("TTYSpawn PTY is closed") from e
            raise

    async def sendline(self, line: str):
        await self.send(line + "\n")

    async def wait(self):
        if self._proc is None:
            raise RuntimeError("TTYSpawn is not started")
        return await self._proc.wait()

    def is_terminated(self) -> bool:
        """Return whether the managed shell process has exited."""
        return self._proc is None or getattr(self._proc, "returncode", None) is not None

    def get_exit_code(self) -> int | None:
        """Return the managed shell exit code when it is already available."""
        if self._proc is None:
            return None
        return getattr(self._proc, "returncode", None)

    def kill(self):
        """Force-kill the running child process.

        This is best-effort: if the process has already terminated (which can
        happen if *close()* was called elsewhere or the child exited by
        itself) we silently ignore the *ProcessLookupError* raised by
        *asyncio.subprocess.Process.kill()*. This prevents race conditions
        where multiple coroutines attempt to close the same session.
        """
        if self._proc is None:
            # Already closed or never started – nothing to do
            return

        # Only attempt to kill if the process is still running
        if getattr(self._proc, "returncode", None) is None:
            self._signal_process(_SIGKILL)
        self._release_pty_master()

    async def read(self, timeout=None):
        # Return any decoded text the child produced, or None on timeout
        try:
            return await asyncio.wait_for(self._buf.get(), timeout)
        except asyncio.TimeoutError:
            return None

    # backward-compat alias:
    readline = read

    async def read_full_until_idle(self, idle_timeout, total_timeout):
        # Collect child output using iter_until_idle to avoid duplicate logic
        return "".join(
            [
                chunk
                async for chunk in self.read_chunks_until_idle(
                    idle_timeout, total_timeout
                )
            ]
        )

    async def read_chunks_until_idle(self, idle_timeout, total_timeout):
        # Yield each chunk as soon as it arrives until idle or total timeout
        import time

        start = time.monotonic()
        while True:
            if time.monotonic() - start > total_timeout:
                break
            chunk = await self.read(timeout=idle_timeout)
            if chunk is None:
                break
            yield chunk

    # ── internal: stream raw output into the queue ────────────────────
    async def _pump_stdout(self):
        if self._proc is None:
            raise RuntimeError("TTYSpawn is not started")
        reader = self._proc.stdout
        while True:
            chunk = await reader.read(4096)  # grab whatever is ready # type: ignore
            if not chunk:
                break
            self._buf.put_nowait(chunk.decode(self.encoding, "replace"))


# ──────────────────────────── POSIX IMPLEMENTATION ────────────────────


async def _spawn_posix_pty(cmd, cwd, env, echo):
    import pty, asyncio, os, termios

    master, slave = pty.openpty()

    # ── Disable ECHO on the slave side if requested ──
    if not echo:
        attrs = termios.tcgetattr(slave)
        attrs[3] &= ~termios.ECHO  # lflag
        termios.tcsetattr(slave, termios.TCSANOW, attrs)

    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        cwd=cwd,
        env=env,
        close_fds=True,
        start_new_session=True,
    )
    os.close(slave)

    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    master_ref = {"fd": master}

    def _release_master_fd():
        cur = master_ref.get("fd")
        if cur is None:
            return
        # Invalidate before close so later cleanup cannot close a reused fd.
        master_ref["fd"] = None
        try:
            proc._pty_master = None  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            loop.remove_reader(cur)
        except Exception:
            pass
        try:
            os.close(cur)
        except OSError:
            pass

    def _on_data():
        cur = master_ref.get("fd")
        if cur is None:
            reader.feed_eof()
            return
        try:
            data = os.read(cur, 1 << 16)
        except OSError as e:
            if e.errno != errno.EIO:  # EIO == EOF on some systems
                raise
            data = b""
        if data:
            reader.feed_data(data)
        else:
            reader.feed_eof()
            _release_master_fd()

    loop.add_reader(master, _on_data)

    class _Stdin:
        def write(self, d):
            cur = master_ref.get("fd")
            if cur is None:
                raise OSError(errno.EBADF, "PTY master closed")
            os.write(cur, d)

        async def drain(self):
            await asyncio.sleep(0)

    proc.stdin = _Stdin()  # type: ignore
    proc.stdout = reader
    proc._pty_master = master  # type: ignore[attr-defined]
    proc._pty_master_ref = master_ref  # type: ignore[attr-defined]
    return proc


# ──────────────────────────── WINDOWS IMPLEMENTATION ──────────────────


async def _spawn_winpty(cmd, cwd, env, echo):
    # Clean PowerShell startup: no logo, no profile, bypass execution policy for deterministic behavior
    if cmd.strip().lower().startswith("powershell"):
        if "-nolog" not in cmd.lower():
            cmd = cmd.replace("powershell.exe", "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass", 1)

    cols, rows = 80, 25
    child = winpty.PtyProcess.spawn(cmd, dimensions=(rows, cols), cwd=cwd or os.getcwd(), env=env) # type: ignore

    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()

    # winpty's read() has no timeout - it can block forever waiting for data
    # (this is normal for a persistent shell between commands, not a bug by
    # itself). Running it via loop.run_in_executor() uses the loop's default
    # ThreadPoolExecutor, whose worker threads are NOT daemon threads -
    # Python's own atexit hook joins them before the interpreter can exit,
    # so a read that's still blocked when the session is torn down hangs
    # the whole process, not just this session. A dedicated daemon thread
    # doesn't have that problem: if it's still stuck in a blocking read when
    # the process exits, the OS reclaims it along with everything else
    # instead of the interpreter waiting on it.
    stop_reading = threading.Event()

    def _safe_call_soon(fn, *args):
        # The event loop may already be closed by the time this fires - e.g.
        # the thread was blocked in child.read() when the session closed and
        # only wakes up afterwards. That's expected, not an error.
        try:
            loop.call_soon_threadsafe(fn, *args)
        except RuntimeError:
            pass

    def _reader_thread():
        while not stop_reading.is_set():
            try:
                data = child.read(1 << 16)
            except EOFError:
                break
            except Exception:
                if stop_reading.is_set():
                    break
                time.sleep(0.01)
                continue
            if data:
                encoded = data.encode("utf-8") if isinstance(data, str) else data
                _safe_call_soon(reader.feed_data, encoded)
            elif not child.isalive():
                break
        _safe_call_soon(reader.feed_eof)

    threading.Thread(target=_reader_thread, daemon=True, name="tty-reader").start()

    class _Stdin:
        def write(self, d):
            # Use winpty's write method, not os.write
            if isinstance(d, bytes):
                d = d.decode('utf-8', errors='replace')
            # Windows needs \r\n for proper line endings
            if _IS_WIN:
              d = d.replace('\n', '\r\n')
            child.write(d)

        async def drain(self):
            await asyncio.sleep(0.01)  # Give write time to complete

    class _Proc:
        def __init__(self):
            self.stdin = _Stdin()  # type: ignore
            self.stdout = reader
            self.pid = child.pid
            self.returncode = None

        async def wait(self):
            while child.isalive():
                await asyncio.sleep(0.2)
            self.returncode = 0
            return 0

        def terminate(self):
            stop_reading.set()
            if child.isalive():
                child.terminate()

        def kill(self):
            stop_reading.set()
            if child.isalive():
                child.kill()

    return _Proc()


# ───────────────────────── INTERACTIVE DRIVER ─────────────────────────
if __name__ == "__main__":

    async def interactive_shell():
        shell_cmd, prompt_hint = ("powershell.exe", ">") if _IS_WIN else ("/bin/bash", "$")

        # echo=False → suppress the shell’s own echo of commands
        term = TTYSession(shell_cmd)
        await term.start()

        timeout = 1.0

        print(f"Connected to {shell_cmd}.")
        print("Type commands for the shell.")
        print("• /t=<seconds>  → change idle timeout")
        print("• /exit         → quit helper\n")

        await term.sendline(" ")
        print(await term.read_full_until_idle(timeout, timeout), end="", flush=True)

        while True:
            try:
                user = input(f"(timeout={timeout}) {prompt_hint} ")
            except (EOFError, KeyboardInterrupt):
                print("\nLeaving…")
                break

            if user.lower() == "/exit":
                break
            if user.startswith("/t="):
                try:
                    timeout = float(user.split("=", 1)[1])
                    print(f"[helper] idle timeout set to {timeout}s")
                except ValueError:
                    print("[helper] invalid number")
                continue

            idle_timeout = timeout
            total_timeout = 10 * idle_timeout
            if user == "":
                # Just read output, do not send empty line
                async for chunk in term.read_chunks_until_idle(
                    idle_timeout, total_timeout
                ):
                    print(chunk, end="", flush=True)
            else:
                await term.sendline(user)
                async for chunk in term.read_chunks_until_idle(
                    idle_timeout, total_timeout
                ):
                    print(chunk, end="", flush=True)

        await term.sendline("exit")
        await term.wait()

    asyncio.run(interactive_shell())

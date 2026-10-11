"""Agent Zero tray launcher: starts the server hidden and shows a tray icon.

Run by pythonw.exe from the Start menu entry the installer creates. It:
- starts Agent Zero like the start-at-logon launcher (plugins/_autostart),
  unless it already answers on its port,
- shows a tray icon: left click opens Agent Zero in the browser; the right-
  click menu has Open, Settings and Quit (Quit stops the server it started),
- uses only the standard library (ctypes); no extra packages.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import importlib.util
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "Agent Zero"

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_DESTROY, WM_COMMAND, WM_USER, WM_LBUTTONUP, WM_RBUTTONUP, WM_CLOSE = 0x0002, 0x0111, 0x0400, 0x0202, 0x0205, 0x0010
WM_TRAY = WM_USER + 20
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4
TPM_RIGHTBUTTON, TPM_BOTTOMALIGN = 0x0002, 0x0020
MF_STRING, MF_SEPARATOR = 0x0, 0x800
IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x10, 0x40
IDI_APPLICATION = 32512
MENU_OPEN, MENU_SETTINGS, MENU_QUIT = 1, 2, 3

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON), ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
                ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT), ("uFlags", wt.UINT),
                ("uCallbackMessage", wt.UINT), ("hIcon", wt.HICON), ("szTip", ctypes.c_wchar * 128),
                ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD), ("szInfo", ctypes.c_wchar * 256),
                ("uVersion", wt.UINT), ("szInfoTitle", ctypes.c_wchar * 64), ("dwInfoFlags", wt.DWORD),
                ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wt.HICON)]


def _autostart_module():
    """The start-at-logon launcher: one implementation of starting the server."""
    path = ROOT / "plugins" / "_autostart" / "launch_agent_zero.pyw"
    spec = importlib.util.spec_from_loader("a0_launch", loader=None)
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(path)
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
    return module


def url(port: int, path: str = "") -> str:
    return f"http://localhost:{port}/{path}"


class Tray:
    def __init__(self, port: int, server: subprocess.Popen | None):
        self.port, self.server = port, server
        self._proc = WNDPROC(self._wndproc)  # keep a reference: ctypes callbacks must outlive the window
        hinst = kernel32.GetModuleHandleW(None)
        cls = WNDCLASSW(lpfnWndProc=self._proc, hInstance=hinst, lpszClassName="AgentZeroTray")
        user32.RegisterClassW(ctypes.byref(cls))
        self.hwnd = user32.CreateWindowExW(0, "AgentZeroTray", APP_NAME, 0, 0, 0, 0, 0, None, None, hinst, None)
        self.nid = NOTIFYICONDATAW(cbSize=ctypes.sizeof(NOTIFYICONDATAW), hWnd=self.hwnd, uID=1,
                                   uFlags=NIF_MESSAGE | NIF_ICON | NIF_TIP, uCallbackMessage=WM_TRAY,
                                   hIcon=self._icon(), szTip=f"{APP_NAME} - localhost:{port}")
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self.nid))

    def _icon(self):
        ico = ROOT / "installer" / "agent-zero.ico"
        if ico.is_file():
            handle = user32.LoadImageW(None, str(ico), IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if handle:
                return handle
        return user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))

    def _menu(self):
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, MF_STRING, MENU_OPEN, "Open Agent Zero")
        user32.AppendMenuW(menu, MF_STRING, MENU_SETTINGS, "Settings")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, MENU_QUIT, "Quit" if self.server else "Close this tray icon")
        point = wt.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        user32.SetForegroundWindow(self.hwnd)
        user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_BOTTOMALIGN, point.x, point.y, 0, self.hwnd, None)
        user32.DestroyMenu(menu)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            if lparam == WM_LBUTTONUP:
                webbrowser.open(url(self.port))
            elif lparam == WM_RBUTTONUP:
                self._menu()
            return 0
        if msg == WM_COMMAND:
            command = wparam & 0xFFFF
            if command == MENU_OPEN:
                webbrowser.open(url(self.port))
            elif command == MENU_SETTINGS:
                webbrowser.open(url(self.port, "#settings"))
            elif command == MENU_QUIT:
                self.quit()
            return 0
        if msg == WM_DESTROY:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self.nid))
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def quit(self):
        if self.server and self.server.poll() is None:
            self.server.terminate()
            try:
                self.server.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.server.kill()
        user32.DestroyWindow(self.hwnd)

    def run(self):
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


def start_server(launch) -> subprocess.Popen | None:
    """Start Agent Zero hidden unless it already answers on its port."""
    import os

    port = launch.web_ui_port()
    if launch.already_running(port):
        return None
    log = launch.open_log()
    log.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] tray launcher: starting Agent Zero on port {port}\n")
    log.flush()
    return subprocess.Popen(
        [launch.python_exe(), "run_ui.py"], cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=log,
        stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
    )


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    launch = _autostart_module()
    server = None if "--no-server" in argv else start_server(launch)
    tray = Tray(launch.web_ui_port(), server)
    if "--smoke" in argv:  # tests: show the icon briefly, then clean up
        user32.PostMessageW(tray.hwnd, WM_CLOSE, 0, 0)
    tray.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

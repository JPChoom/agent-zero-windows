"""Synthetic mouse and keyboard input for the real Windows desktop.

Uses SendInput via ctypes rather than pywin32's win32api.mouse_event /
keybd_event. Those are the legacy Win32 entry points; SendInput is the
supported replacement and is delivered atomically as a single input block,
which matters for modifier combinations (a ctrl+c sent as separate legacy
calls can interleave with real user input and land as a bare 'c').

Mouse coordinates are absolute and in *screen* space (native resolution).
SendInput's absolute mode wants 0..65535 normalised units, so callers pass
real pixels and the conversion happens here - the alternative, exposing
normalised units, would be a constant source of off-by-a-screen bugs.

This module performs no permission checks: gating (control_enabled, kill
switch, audit) belongs to the caller, so the tool and the web endpoint both
enforce it in one place each rather than trusting this layer.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes


# --- SendInput structures -------------------------------------------------

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000
# Normalises absolute coordinates against the whole virtual desktop rather
# than the primary monitor. Without it, an absolute move can only ever
# address the primary screen.
MOUSEEVENTF_VIRTUALDESK = 0x4000

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

WHEEL_DELTA = 120


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]


# Virtual-key codes for the named keys a model is likely to ask for.
VK_CODES: dict[str, int] = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
    "shift": 0x10, "ctrl": 0x11, "control": 0x11, "alt": 0x12,
    "pause": 0x13, "capslock": 0x14, "esc": 0x1B, "escape": 0x1B,
    "space": 0x20, "pageup": 0x21, "pagedown": 0x22, "end": 0x23,
    "home": 0x24, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "printscreen": 0x2C, "insert": 0x2D, "delete": 0x2E, "del": 0x2E,
    "win": 0x5B, "windows": 0x5B, "super": 0x5B, "menu": 0x5D,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
    "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
    "f11": 0x7A, "f12": 0x7B,
}

MOUSE_BUTTONS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


class InputError(ValueError):
    """Raised for a malformed or out-of-range input request."""


_USER32 = None


def _user32():
    """user32 with the signatures this module uses declared.

    Without argtypes, ctypes marshals arguments as C int, which truncates
    64-bit pointers - the kind of fault that appears to work until it
    silently corrupts. Declared once and cached rather than re-resolved
    per event.
    """
    global _USER32
    if _USER32 is None:
        lib = ctypes.WinDLL("user32", use_last_error=True)
        lib.SendInput.argtypes = (wintypes.UINT, ctypes.c_void_p, ctypes.c_int)
        lib.SendInput.restype = wintypes.UINT
        lib.GetSystemMetrics.argtypes = (ctypes.c_int,)
        lib.GetSystemMetrics.restype = ctypes.c_int
        lib.GetForegroundWindow.restype = wintypes.HWND
        lib.SetForegroundWindow.argtypes = (wintypes.HWND,)
        lib.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
        lib.GetWindowTextW.restype = ctypes.c_int
        lib.IsWindowVisible.argtypes = (wintypes.HWND,)
        lib.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
        lib.AttachThreadInput.argtypes = (
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.BOOL,
        )
        lib.GetWindowThreadProcessId.argtypes = (
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        )
        lib.GetWindowThreadProcessId.restype = wintypes.DWORD
        _USER32 = lib
    return _USER32


def get_primary_screen_size() -> tuple[int, int]:
    user32 = _user32()
    return int(user32.GetSystemMetrics(SM_CXSCREEN)), int(
        user32.GetSystemMetrics(SM_CYSCREEN)
    )


def get_virtual_bounds() -> tuple[int, int, int, int]:
    """(origin_x, origin_y, width, height) of the whole virtual desktop.

    The origin is not always (0, 0): a monitor placed left of the primary
    gives a negative SM_XVIRTUALSCREEN (-1920 on the development machine,
    which has three screens spanning 5760x1080).
    """
    user32 = _user32()
    return (
        int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN)),
        int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN)),
        int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)),
        int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)),
    )


def get_screen_size() -> tuple[int, int]:
    """Size of the addressable coordinate space (the whole virtual desktop).

    Callers pass 0-based coordinates within this space, matching what a
    capture of the virtual desktop looks like, rather than Windows' own
    virtual-screen coordinates which can be negative.
    """
    _, _, width, height = get_virtual_bounds()
    return width, height


def _send(*inputs: _INPUT) -> None:
    user32 = _user32()
    count = len(inputs)
    array = (_INPUT * count)(*inputs)
    sent = user32.SendInput(count, array, ctypes.sizeof(_INPUT))
    if sent != count:
        raise OSError(
            f"SendInput delivered {sent}/{count} events "
            f"(error {ctypes.get_last_error()})"
        )


def _mouse_input(dx: int, dy: int, flags: int, data: int = 0) -> _INPUT:
    return _INPUT(
        type=INPUT_MOUSE,
        union=_INPUTUNION(
            mi=_MOUSEINPUT(dx, dy, data, flags, 0, ctypes.pointer(ctypes.c_ulong(0)))
        ),
    )


def _key_input(vk: int, flags: int = 0, scan: int = 0) -> _INPUT:
    return _INPUT(
        type=INPUT_KEYBOARD,
        union=_INPUTUNION(
            ki=_KEYBDINPUT(vk, scan, flags, 0, ctypes.pointer(ctypes.c_ulong(0)))
        ),
    )


def _to_absolute(x: int, y: int) -> tuple[int, int]:
    """Convert 0-based virtual-desktop pixels to SendInput's 0..65535 range.

    Input coordinates are 0-based within the captured virtual desktop, so
    (0, 0) is its top-left corner whichever monitor that happens to be on.
    Windows' own virtual-screen space can start at a negative x, so the
    origin is added back here rather than exposed to callers - a screenshot
    has no negative pixels, and asking a model to reason about them would
    invite exactly the off-by-a-monitor errors this avoids.
    """
    _, _, width, height = get_virtual_bounds()
    if not (0 <= x < width and 0 <= y < height):
        raise InputError(
            f"({x}, {y}) is outside the {width}x{height} virtual desktop"
        )
    # No origin offset is applied: MOUSEEVENTF_VIRTUALDESK makes the
    # 0..65535 range span the virtual desktop itself, so its 0 already means
    # the left edge - i.e. SM_XVIRTUALSCREEN, not Windows' absolute 0. The
    # origin still matters for callers converting window positions, which is
    # why get_virtual_bounds() exposes it.
    # The -1 divisor maps the last pixel to exactly 65535 rather than
    # rounding short of the edge.
    return (
        int(round(x * 65535 / max(1, width - 1))),
        int(round(y * 65535 / max(1, height - 1))),
    )


def move(x: int, y: int) -> None:
    ax, ay = _to_absolute(int(x), int(y))
    _send(_mouse_input(ax, ay, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK))


def click(x: int, y: int, button: str = "left", clicks: int = 1) -> None:
    button = (button or "left").strip().lower()
    if button not in MOUSE_BUTTONS:
        raise InputError(
            f"unknown mouse button {button!r}; use one of "
            f"{', '.join(sorted(MOUSE_BUTTONS))}"
        )
    clicks = int(clicks)
    if not 1 <= clicks <= 3:
        raise InputError("clicks must be between 1 and 3")

    down, up = MOUSE_BUTTONS[button]
    ax, ay = _to_absolute(int(x), int(y))
    _send(_mouse_input(ax, ay, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK))
    for index in range(clicks):
        if index:
            # Stay inside the double-click interval so consecutive clicks
            # register as a double click rather than two separate ones.
            time.sleep(0.05)
        _send(_mouse_input(0, 0, down), _mouse_input(0, 0, up))


def scroll(x: int, y: int, amount: int) -> None:
    """Positive amount scrolls up, negative down (in wheel notches)."""
    ax, ay = _to_absolute(int(x), int(y))
    _send(_mouse_input(ax, ay, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK))
    _send(_mouse_input(0, 0, MOUSEEVENTF_WHEEL, int(amount) * WHEEL_DELTA))


def type_text(text: str) -> None:
    """Type a literal string.

    Sent as Unicode scan codes rather than virtual-key codes so the output
    doesn't depend on the active keyboard layout - a VK-based approach types
    the wrong characters on a non-US layout.

    Sent one character at a time rather than as a single batched array.
    A batch is delivered atomically, and rich text controls (Windows 11's
    Notepad uses RichEditD2DPT) do not reliably keep up: an observed run of
    "Hello from Agent Zero" arrived as "Hello " followed by fifteen copies
    of the final character - the right number of events, the wrong content.
    Per-character delivery with a short gap is what every mature automation
    library does, for this reason.
    """
    for char in str(text):
        _send(
            _key_input(0, KEYEVENTF_UNICODE, ord(char)),
            _key_input(0, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, ord(char)),
        )
        time.sleep(TYPE_CHAR_INTERVAL)


def parse_hotkey(combo: str) -> list[int]:
    keys = [part.strip().lower() for part in str(combo).split("+") if part.strip()]
    if not keys:
        raise InputError("empty key combination")
    codes: list[int] = []
    for key in keys:
        if key in VK_CODES:
            codes.append(VK_CODES[key])
        elif len(key) == 1:
            # Letters/digits map to their uppercase ASCII virtual-key code.
            codes.append(ord(key.upper()))
        else:
            raise InputError(
                f"unknown key {key!r}; use a single character or one of "
                f"{', '.join(sorted(VK_CODES))}"
            )
    return codes


def press_keys(combo: str) -> None:
    """Press a combination such as 'ctrl+c', 'alt+tab', or 'enter'."""
    codes = parse_hotkey(combo)
    events = [_key_input(code) for code in codes]
    events += [_key_input(code, KEYEVENTF_KEYUP) for code in reversed(codes)]
    _send(*events)


# --- window targeting -----------------------------------------------------
#
# Input is delivered to whatever holds focus. A test that launched Notepad
# and typed into it appended the text to a *pre-existing, unsaved* Notepad
# document instead, because Start-Process did not bring the intended window
# forward. Typing at ambient focus is not safe on a real desktop, so the
# caller can name a target window and the action is refused if that window
# cannot be brought to the front.

SW_RESTORE = 9

# Interval between characters. Long enough for rich text controls to keep
# up, short enough that a sentence still types in well under a second.
TYPE_CHAR_INTERVAL = 0.006


def get_foreground_window() -> tuple[int, str]:
    """Return (hwnd, title) of the window that will receive input."""
    user32 = _user32()
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return 0, ""
    buffer = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buffer, 512)
    return int(hwnd), buffer.value


def find_windows(title_substring: str) -> list[tuple[int, str]]:
    """Visible top-level windows whose title contains `title_substring`."""
    needle = str(title_substring or "").strip().lower()
    matches: list[tuple[int, str]] = []
    user32 = _user32()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            buffer = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buffer, 512)
            title = buffer.value
            if title and needle in title.lower():
                matches.append((int(hwnd), title))
        return True

    user32.EnumWindows(_enum, 0)
    return matches


def focus_window(title_substring: str, timeout: float = 2.0) -> str:
    """Bring the window matching `title_substring` to the foreground.

    Returns its title. Raises InputError if no window matches, if several
    do (ambiguous target - refusing beats guessing which document to type
    into), or if the window will not come forward.
    """
    matches = find_windows(title_substring)
    if not matches:
        raise InputError(f"no visible window matching {title_substring!r}")
    if len(matches) > 1:
        titles = ", ".join(repr(title) for _, title in matches[:5])
        raise InputError(
            f"{len(matches)} windows match {title_substring!r} ({titles}); "
            "use a more specific title"
        )

    hwnd, title = matches[0]
    user32 = _user32()

    # SetForegroundWindow is refused unless the calling thread shares input
    # state with the current foreground window, so attach to it first and
    # detach afterwards regardless of the outcome.
    current = user32.GetForegroundWindow()
    our_thread = ctypes.windll.kernel32.GetCurrentThreadId()
    their_thread = user32.GetWindowThreadProcessId(current, None) if current else 0

    attached = False
    if their_thread and their_thread != our_thread:
        attached = bool(user32.AttachThreadInput(our_thread, their_thread, True))
    try:
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(our_thread, their_thread, False)

    # Verified rather than assumed: SetForegroundWindow can return success
    # and still not change focus under Windows' foreground lock.
    deadline = time.time() + timeout
    while time.time() < deadline:
        if user32.GetForegroundWindow() == hwnd:
            return title
        time.sleep(0.05)
    raise InputError(
        f"could not bring {title!r} to the foreground (Windows refused the "
        "focus change); click the window yourself and retry"
    )


def list_monitors():
    """Monitors in 0-based virtual-desktop coordinates.

    Re-exported from helpers.capture so there is one implementation: the
    viewer maps clicks with it and the capture path crops with it, and two
    copies drifting apart would put clicks on the wrong screen.
    """
    from plugins._win_desktop.helpers.capture import list_monitors as _impl

    return _impl()


def drag(
    start_x: int, start_y: int, end_x: int, end_y: int,
    button: str = "left", steps: int = 24,
) -> None:
    """Press at the start point, move to the end point, release.

    The pointer is moved in steps rather than teleported: applications track
    WM_MOUSEMOVE to decide a drag has begun, and a single jump from press to
    release is frequently interpreted as a click on the destination instead.
    Window dragging and text selection both depend on the intermediate moves.
    """
    button = (button or "left").strip().lower()
    if button not in MOUSE_BUTTONS:
        raise InputError(f"unknown mouse button {button!r}")
    steps = max(2, min(int(steps), 200))

    down, up = MOUSE_BUTTONS[button]
    start = _to_absolute(int(start_x), int(start_y))
    end = _to_absolute(int(end_x), int(end_y))

    _send(_mouse_input(*start, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK))
    time.sleep(0.02)
    _send(_mouse_input(0, 0, down))
    time.sleep(0.05)
    for index in range(1, steps + 1):
        fraction = index / steps
        point = (
            int(round(start[0] + (end[0] - start[0]) * fraction)),
            int(round(start[1] + (end[1] - start[1]) * fraction)),
        )
        _send(
            _mouse_input(
                *point,
                MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
            )
        )
        time.sleep(0.008)
    time.sleep(0.05)
    _send(_mouse_input(0, 0, up))


def get_clipboard_text() -> str:
    """Read the clipboard as text, or "" if it holds something else."""
    import win32clipboard
    import win32con as wc

    win32clipboard.OpenClipboard()
    try:
        if not win32clipboard.IsClipboardFormatAvailable(wc.CF_UNICODETEXT):
            return ""
        return win32clipboard.GetClipboardData(wc.CF_UNICODETEXT) or ""
    finally:
        win32clipboard.CloseClipboard()


def set_clipboard_text(text: str) -> None:
    import win32clipboard
    import win32con as wc

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(wc.CF_UNICODETEXT, str(text))
    finally:
        win32clipboard.CloseClipboard()

"""Key names and combinations to PC (set 1) scancodes for VBoxManage keyboardputscancode.

A spec is one or more steps separated by spaces; a step is keys joined by "+",
pressed in order and released in reverse: "ctrl+alt+del", "win+r", "alt+f4",
"shift+tab tab enter". Typing text is `keyboardputstring`, not this.
"""

from __future__ import annotations

_PLAIN = {
    "esc": 0x01, "escape": 0x01, "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06, "6": 0x07, "7": 0x08,
    "8": 0x09, "9": 0x0A, "0": 0x0B, "-": 0x0C, "minus": 0x0C, "=": 0x0D, "equals": 0x0D, "backspace": 0x0E,
    "tab": 0x0F, "q": 0x10, "w": 0x11, "e": 0x12, "r": 0x13, "t": 0x14, "y": 0x15, "u": 0x16, "i": 0x17,
    "o": 0x18, "p": 0x19, "[": 0x1A, "]": 0x1B, "enter": 0x1C, "return": 0x1C, "ctrl": 0x1D, "control": 0x1D,
    "a": 0x1E, "s": 0x1F, "d": 0x20, "f": 0x21, "g": 0x22, "h": 0x23, "j": 0x24, "k": 0x25, "l": 0x26,
    ";": 0x27, "'": 0x28, "`": 0x29, "shift": 0x2A, "\\": 0x2B, "z": 0x2C, "x": 0x2D, "c": 0x2E, "v": 0x2F,
    "b": 0x30, "n": 0x31, "m": 0x32, ",": 0x33, ".": 0x34, "/": 0x35, "rshift": 0x36, "alt": 0x38,
    "space": 0x39, "capslock": 0x3A, "f1": 0x3B, "f2": 0x3C, "f3": 0x3D, "f4": 0x3E, "f5": 0x3F, "f6": 0x40,
    "f7": 0x41, "f8": 0x42, "f9": 0x43, "f10": 0x44, "numlock": 0x45, "scrolllock": 0x46, "f11": 0x57, "f12": 0x58,
}
# Extended keys: sent with an E0 prefix.
_EXTENDED = {
    "home": 0x47, "up": 0x48, "pageup": 0x49, "pgup": 0x49, "left": 0x4B, "right": 0x4D, "end": 0x4F,
    "down": 0x50, "pagedown": 0x51, "pgdn": 0x51, "insert": 0x52, "ins": 0x52, "delete": 0x53, "del": 0x53,
    "win": 0x5B, "windows": 0x5B, "super": 0x5B, "meta": 0x5B, "rwin": 0x5C, "menu": 0x5D, "apps": 0x5D,
    "ralt": 0x38, "altgr": 0x38, "rctrl": 0x1D,
}
MAX_STEPS = 50


def _codes(name: str, release: bool) -> list[str]:
    key = name.strip().lower()
    if key in _PLAIN:
        code = _PLAIN[key] | (0x80 if release else 0)
        return [f"{code:02x}"]
    if key in _EXTENDED:
        code = _EXTENDED[key] | (0x80 if release else 0)
        return ["e0", f"{code:02x}"]
    raise ValueError(f"Unknown key '{name}'. Known: letters, digits, f1-f12, enter, tab, esc, space, backspace, "
                     "arrows (up/down/left/right), home/end/pageup/pagedown, insert/delete, ctrl, alt, shift, win.")


def scancodes(spec: str) -> list[str]:
    steps = [step for step in str(spec or "").split() if step]
    if not steps:
        raise ValueError("No keys given.")
    if len(steps) > MAX_STEPS:
        raise ValueError(f"At most {MAX_STEPS} key steps at once.")
    codes: list[str] = []
    for step in steps:
        names = [n for n in step.split("+") if n]
        if not names:
            raise ValueError("To type a '+' character, use vm type.")
        for name in names:
            codes += _codes(name, release=False)
        for name in reversed(names):
            codes += _codes(name, release=True)
    return codes

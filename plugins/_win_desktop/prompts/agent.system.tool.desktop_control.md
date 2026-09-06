### desktop_control
move the mouse, click, scroll, or type on the user's real Windows desktop
args: `action`, optional `window`, `x`, `y`, `button`, `clicks`, `amount`, `text`, `keys`

actions:
- `focus` - needs `window`; brings a window to the front
- `move` - needs `x`, `y`
- `click` - needs `x`, `y`; optional `button` (`left`|`right`|`middle`), `clicks` (1-3)
- `scroll` - needs `x`, `y`, `amount` (positive scrolls up, negative down)
- `type` - needs `text`, types it literally into the focused window
- `key` - needs `keys`, a combination like `ctrl+c`, `alt+tab`, `enter`, `f5`

targeting the right window:
- input always goes to whichever window has focus. Pass `window` with part of
  the target's title bar text on any action to focus it first; the action is
  refused if no window matches, if several do, or if Windows will not bring it
  forward
- ALWAYS pass `window` when typing or pressing keys. Without it the text lands
  in whatever happened to be focused - this has appended text to a user's
  unrelated unsaved document
- launching an application does not reliably focus it, and an existing window
  of that application may be reused. After launching, take a
  `desktop_screenshot` and use `focus` before typing

rules:
- coordinates are in screen space at the resolution reported by
  `desktop_screenshot`, NOT the size of the attached image
- always call `desktop_screenshot` first to see where things are, and again
  afterwards to confirm the action did what you expected
- this drives the user's real machine: it can close windows, discard unsaved
  work, or confirm dialogs. Prefer a terminal command or a file edit when one
  would achieve the same result more reliably
- never use it to enter passwords or accept security or permission prompts
- disabled unless the user turns it on, and blocked while the kill switch is
  active; if it reports being disabled, tell the user rather than retrying

example:
~~~json
{
  "thoughts": ["Notepad is open; focus it before typing so the text cannot land elsewhere."],
  "headline": "Typing into Notepad",
  "tool_name": "desktop_control",
  "tool_args": {
    "action": "type",
    "window": "Notepad",
    "text": "Hello"
  }
}
~~~

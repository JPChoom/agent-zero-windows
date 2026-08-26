### desktop_control
move the mouse, click, scroll, or type on the user's real Windows desktop
args: `action`, optional `x`, `y`, `button`, `clicks`, `amount`, `text`, `keys`

actions:
- `move` - needs `x`, `y`
- `click` - needs `x`, `y`; optional `button` (`left`|`right`|`middle`), `clicks` (1-3)
- `scroll` - needs `x`, `y`, `amount` (positive scrolls up, negative down)
- `type` - needs `text`, types it literally at the current focus
- `key` - needs `keys`, a combination like `ctrl+c`, `alt+tab`, `enter`, `f5`

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
  "thoughts": ["The Save button is at (840, 512) in the screenshot."],
  "headline": "Clicking Save",
  "tool_name": "desktop_control",
  "tool_args": {
    "action": "click",
    "x": 840,
    "y": 512
  }
}
~~~

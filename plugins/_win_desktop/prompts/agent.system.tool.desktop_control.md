### desktop_control
mouse, scroll and keyboard on the user's real Windows desktop
args: `action`, optional `window`, `x`, `y`, `button`, `clicks`, `amount`, `text`, `keys`
actions: `focus` (needs `window`), `move` (`x`,`y`), `click` (`x`,`y`, `button` left|right|middle, `clicks` 1-3), `scroll` (`x`,`y`, `amount` +up/-down), `type` (`text`, literal), `key` (`keys` e.g. `ctrl+c`, `alt+tab`, `enter`)
- input goes to the focused window: ALWAYS pass `window` (part of its title) when typing or pressing keys - without it text has landed in a user's unrelated unsaved document. Refused if no window or several match
- launching an app does not reliably focus it: take a `desktop_screenshot`, then `focus`, before typing
- coordinates are in desktop space at the size `desktop_screenshot` reports (all monitors as one area; x beyond one monitor is normal), not the attached image's size
- screenshot before acting and again after to confirm
- it drives the real machine (can close windows, lose unsaved work, confirm dialogs): prefer a terminal command or file edit when one works
- never enter passwords or accept security/permission prompts; if it reports disabled or kill-switch blocked, tell the user instead of retrying
~~~json
{"thoughts": ["Focus Notepad so the text can't land elsewhere."], "headline": "Typing into Notepad", "tool_name": "desktop_control",
 "tool_args": {"action": "type", "window": "Notepad", "text": "Hello"}}
~~~

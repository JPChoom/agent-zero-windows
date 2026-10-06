### desktop_control
real mouse/keyboard on the user's desktop (moves the pointer, takes focus); prefer computer_use, which works in the background
args: `action`: `focus` (`window`), `move`/`click` (`x`,`y`, `button`, `clicks` 1-3), `scroll` (`x`,`y`, `amount` +up/-down), `type` (`text`), `key` (`keys` e.g. `ctrl+c`)
- ALWAYS pass `window` (part of its title) to type or press keys - otherwise input lands in whatever has focus, e.g. the user's unsaved document
- coordinates: desktop space at the size `desktop_screenshot` reports (all monitors), not the image's size; screenshot before and after acting
- can close windows and lose unsaved work: prefer a terminal command or file edit when one works
- never enter passwords or accept security prompts; if disabled or kill-switch blocked, tell the user
~~~json
{"thoughts": ["Type into Notepad only"], "headline": "Typing into Notepad", "tool_name": "desktop_control",
 "tool_args": {"action": "type", "window": "Notepad", "text": "Hello"}}
~~~

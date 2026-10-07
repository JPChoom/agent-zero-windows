### desktop_control
real mouse/keyboard on the user's desktop (moves the pointer, takes focus); last resort after computer_use
args: `action`: `focus` (`window`), `move`/`click` (`x`,`y`, `button`, `clicks` 1-3), `scroll` (`x`,`y`, `amount` +up/-down), `type` (`text`), `key` (`keys` e.g. `ctrl+c`)
- ALWAYS pass `window` (part of its title) to type or press keys, else input lands wherever focus is, e.g. the user's unsaved document
- coordinates: desktop space at the size `desktop_screenshot` reports, not the image's size; screenshot before and after
- can close windows and lose work; never enter passwords or accept security prompts; if disabled or kill-switch blocked, tell the user

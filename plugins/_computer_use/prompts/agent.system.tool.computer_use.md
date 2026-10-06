### computer_use
operate Windows apps via UI Automation in the background (no mouse move, no focus steal)
args: `action`, optional `pid`, `window_id`, `element_token`, `text`, `value`, `key`, `keys`, `x`, `y`, `direction`, `path`, `app`, `screenshot`, `delivery`
look: `apps`, `windows`, `inspect` (lists `token | role | label | value`), `screenshot` (then vision_load); act (pass `pid`): `launch` (`app`), `click`/`set_value` (`element_token`), `type`, `key`, `hotkey`, `scroll`, `menu` (`path`), `focus`, `close` (own apps only)
- inspect first, act by token, inspect again to confirm; tokens expire at the next inspect
- an app that was already running is the user's (unsaved work): prefer windows you launched; acting on theirs asks them
- `delivery`: "foreground" only after a result says background delivery failed (asks the user)
- web pages: browser tool; commands: terminal tool. Terminals, sign-in/password windows and password fields are refused

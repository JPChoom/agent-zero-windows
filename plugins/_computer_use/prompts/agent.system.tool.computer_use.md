### computer_use
operate Windows apps via UI Automation in the background (no mouse move, no focus steal)
look: `apps`, `windows`, `inspect` (`pid`,`window_id`; lists `token | role | label | value`), `screenshot` (then vision_load)
act (always pass `pid`): `launch` (`app`), `click`/`set_value` (`element_token`), `type` (`text`), `key`, `hotkey` (`keys`), `scroll` (`direction`), `menu` (`path`), `focus`, `close` (own apps only)
- inspect first, act by token, inspect again to confirm; tokens expire at the next inspect
- an app that was already running is the user's (unsaved work): prefer windows you launched; acting on theirs asks them
- use `delivery`: "foreground" only after a result says background delivery failed (asks the user)
- web pages: browser tool; commands: terminal tool. Terminals, sign-in/password windows and password fields are refused

### computer_use
operate Windows apps via UI Automation in the background (no mouse move, no focus steal)
args: `action`, optional `pid`, `window_id`, `element_token`, `text`, `value`, `key`, `keys`, `x`, `y`, `direction`, `path`, `app`, `screenshot`, `delivery`
look: `apps`, `windows`, `inspect` (`token | role | label | value`), `screenshot`; act (pass `pid`): `launch` (`app`), `click`/`set_value` (`element_token`), `type`, `key`, `hotkey`, `scroll`, `menu` (`path`), `focus`, `close` (own apps)
- inspect, act by token, inspect again; tokens expire at the next inspect
- an already-running app is the user's (unsaved work): prefer windows you launched; acting on theirs asks them
- `delivery` "foreground" only after a result says background failed (asks the user); terminals, sign-in/password windows and fields are refused

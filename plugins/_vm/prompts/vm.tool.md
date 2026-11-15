### vm
control installed VirtualBox VMs (Windows or Linux)
args: `action`, `vm` (name from `list`), then per action:
- `list`, `status`, `start` (`window: true`), `stop` (`how`: shutdown|poweroff|save|pause|resume|reset), `snapshots`, `snapshot`/`restore` (`name`)
- `screenshot` (then vision_load it), `type` (`text`), `keys` ("ctrl+alt+del", "win+r enter"), `mouse` (`x`, `y` screenshot pixels, `click`: left|right|double|drag|none, `to_x`/`to_y`, `scroll`)
- in the guest (Guest Additions + account): `run` (`command`, `shell`: auto|powershell|cmd|sh|bash, `timeout`), `read`/`write` (`path`, `content`), `copy_in`/`copy_out` (`host_path`, `guest_path`); account from Secrets VM_USER/VM_PASSWORD or `user` + `password` as §§secret(NAME)
- sandbox (clones A0W made): `clone` (linked, sealed), `clones`, `reset_clone`, `delete_clone`, `net` (`mode`: sealed|internet), `isolation`
- an isolated VM (no writable share/guest→host clipboard, loopback off, sealed or NAT net) skips safety checks: be bold inside it, careful on the host and non-isolated VMs
prefer `run`; use screen, keys and mouse for boot, installer and login screens
~~~json
{"tool_name": "vm", "tool_args": {"action": "run", "vm": "Win11", "command": "Get-Process | Select-Object -First 5"}}
~~~

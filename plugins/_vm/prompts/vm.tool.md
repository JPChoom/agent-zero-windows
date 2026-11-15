### vm
control installed VirtualBox VMs (Windows or Linux)
args: `action`, `vm` (name from `list`), then per action:
- `list`, `status`, `start` (`window: true`), `stop` (`how`: shutdown|poweroff|save|pause|resume|reset), `snapshots`, `snapshot`/`restore` (`name`)
- `screenshot` (then vision_load it), `type` (`text`), `keys` ("ctrl+alt+del", "win+r enter"), `mouse` (`x`, `y` screenshot pixels, `click`: left|right|double|drag|none, `to_x`/`to_y`, `scroll`)
- in the guest (Guest Additions + account): `run` (`command`, `shell`: auto|powershell|cmd|sh|bash, `timeout`), `read`/`write` (`path`, `content`), `copy_in`/`copy_out` (`host_path`, `guest_path`); account from Secrets VM_USER/VM_PASSWORD or `user` + `password` as §§secret(NAME)
- sandbox: `clone` (linked, hardened: no host loopback/shared folders/clipboard), `clones`, `reset_clone` (fresh replacement), `delete_clone` (A0W-made clones only); be bold in clones, careful in other VMs
prefer `run`; use screen, keys and mouse for boot, installer and login screens
~~~json
{"tool_name": "vm", "tool_args": {"action": "run", "vm": "Win11", "command": "Get-Process | Select-Object -First 5"}}
~~~

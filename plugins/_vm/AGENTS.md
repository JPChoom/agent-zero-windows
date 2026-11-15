# VM Plugin DOX

## Purpose

- Own the `vm` tool: full control of installed VirtualBox VMs, Windows or Linux - power, snapshots, screen, keyboard, mouse, and programs and files inside the guest.

## Ownership

- `helpers/vbox.py` owns talking to VirtualBox: `VBoxManage` for listing, power, snapshots, screenshots (`controlvm screenshotpng`), keyboard (`keyboardputstring`, `keyboardputscancode`) and guest control (`guestcontrol run/copyfrom/copyto`); the COM API (pywin32, `VirtualBox.VirtualBox`, a shared session lock) for the mouse and the live Guest Additions run level.
- `helpers/keys.py` owns key names and combinations ("ctrl+alt+del", "win+r") to set-1 scancodes.
- `tools/vm.py` owns the tool's actions, credentials and output; `prompts/vm.tool.md` its description.
- `extensions/python/_functions/_11_tools_prompt/build_prompt/end/_72_include_vm_tool.py` adds that description only when VirtualBox is installed and capability policies do not refuse the tool.

## Local Contracts

- Any installed VM can be controlled (no allowlist; owner decision 2026-11-13). Every action is a normal tool call: the permission mode asks for power, input and guest actions (`_permissions` rules treat `list`, `status`, `snapshots` and `screenshot` as reads), capability ids are `vm:<action>`, and guest output is wrapped as untrusted content like any tool result.
- A VM name from the model is resolved to its UUID (exact name or UUID, case-insensitive) before any command.
- The tool never changes a VM's settings (memory, network, shared folders, clipboard), with one exception: a sandbox clone it made itself.
- Sandbox clones (the disposable dev environment): `clone` makes a linked clone of a golden VM from its current snapshot (or takes `a0w-golden` first), marks it with extradata `A0W/clone-of` = the golden VM's UUID, and hardens it to the **sealed** state - clipboard and drag-and-drop disabled, every shared folder removed, and the network set to `nic1 null` (no host, no LAN, no internet). Only machines carrying that marker can be deleted (`delete_clone`, powers off first), replaced (`reset_clone`), or have their network switched (`net`, `mode` sealed|internet - "internet" is NAT with host loopback off); cloning a clone is refused. The golden VM and the user's other VMs stay under the ordinary rules. The host command floor (`_safety_policy`) does not inspect `vm run`, so commands inside a guest are the guest's problem; guest output is untrusted content like any tool result.
- Isolation and the no-floor exemption: `vm_is_isolated(machine)` returns (isolated, reasons) - isolated means a guest can neither write back to the host nor reach it: no writable shared folder (a read-only one is fine, one-way host->guest ingress), clipboard and drag-and-drop never guest->host, host loopback off, and every adapter sealed (null/none/intnet) or NAT with loopback off (host-only and bridged never qualify; `vm isolation` reports it). `plugins/_infection_check` skips its LLM gate for a `vm` action whose target is isolated (`exempt_isolated_vm` config, default on) - such a guest cannot reach the host, so an injection confined to it has nothing to attack; on any VM not provably isolated the check stays. The predicate reads live state and fails safe (any read error => not isolated). This is the only cross-plugin coupling: `_infection_check` imports `plugins._vm.helpers.vbox`, guarded so an absent VirtualBox just means the check always runs.
- Guest account: `user` / `password` tool args (passwords as `§§secret(NAME)` placeholders, filled in before the tool runs), else Secrets `VM_<NAME>_USER` / `VM_<NAME>_PASSWORD`, then `VM_USER` / `VM_PASSWORD`. A password reaches VBoxManage only through a temporary `--passwordfile`, deleted right after; the tool's log shows it as `***`.
- Inside-the-guest actions need the guest's Guest Additions running, checked by the live COM run level (the version guest property survives a shutdown, so it is not proof). Without them the agent uses screen, keyboard and mouse, which also work at boot menus, installers and login screens.
- Screenshots go to `tmp/vm/` and are looked at with `vision_load`; mouse coordinates are the screenshot's pixels from the top-left (VirtualBox's absolute pointer is 1-based internally). A guest without an absolute pointer gets a clear error.
- `run` reports the guest's exit code (VBoxManage returns it plus 32, capped, so codes of about 94 and above all read as 94).
- `type` and `keys` send US-layout key codes. A guest on another layout (Windows Setup defaults to the installed language, e.g. UK) mistypes `\ | " @ # ~`; prefer forward slashes (`cd` accepts them), `%CD%`, or change the guest layout first.
- Windows only (VirtualBox COM through pywin32); other hypervisors are not supported yet.

## Verification

- `pytest tests/test_vm_tool.py` (a stand-in VBoxManage and COM console; no VM needed).
- Live: `vm list` and `vm status`; then on a VM with Guest Additions and its account: start, screenshot, mouse move, `run`, write/read/copy_out/delete a temp file, shut down.

## Child DOX Index

No child DOX files.

"""Full control of VirtualBox VMs (plugins/_vm), against a stand-in VBoxManage and COM console."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins._vm.helpers import keys, vbox

ROOT = Path(__file__).resolve().parents[1]
WIN = "11111111-1111-1111-1111-111111111111"
LNX = "22222222-2222-2222-2222-222222222222"

STUB = r'''
import json, os, sys
state_file, log_file = os.environ["VBOX_STUB_STATE"], os.environ["VBOX_STUB_LOG"]
state = json.load(open(state_file))
args = sys.argv[1:]
entry = {"args": args}
def save():
    json.dump(state, open(state_file, "w"))
def out(text, code=0):
    with open(log_file, "a") as fh:
        fh.write(json.dumps(entry) + "\n")
    sys.stdout.write(text)
    sys.exit(code)
names = {u: v["name"] for u, v in state["vms"].items()}
if args[:2] == ["list", "vms"]:
    out("".join(f'"{v["name"]}" {{{u}}}\n' for u, v in state["vms"].items()))
if args[:2] == ["list", "runningvms"]:
    out("".join(f'"{v["name"]}" {{{u}}}\n' for u, v in state["vms"].items() if v["state"] == "running"))
uuid = next((a for a in args if a in state["vms"]), "")
vm = state["vms"].get(uuid)
if args[0] == "showvminfo":
    lines = [f'name="{vm["name"]}"', f'ostype="{vm["os"]}"', f'VMState="{vm["state"]}"', 'memory=8192', 'cpus=4', 'nic1="nat"']
    lines += [f'SnapshotName{"" if i == 0 else "-" + str(i)}="{s}"' for i, s in enumerate(vm["snapshots"])]
    lines += [f'SharedFolderNameMachineMapping{i + 1}="{s}"' for i, s in enumerate(vm.get("shared", []))]
    if vm["snapshots"]:
        lines.append(f'CurrentSnapshotName="{vm["snapshots"][-1]}"')
    out("\n".join(lines) + "\n")
if args[0] == "getextradata":
    out(f"Value: {vm['extra'][args[2]]}\n" if args[2] in vm.get("extra", {}) else "No value set!\n")
if args[0] == "setextradata":
    vm.setdefault("extra", {})[args[2]] = args[3]; save(); out("")
if args[0] == "clonevm":
    import uuid as uuid_lib
    new_name = args[args.index("--name") + 1]
    snap = args[args.index("--snapshot") + 1]
    if snap not in vm["snapshots"]:
        out(f"Could not find a snapshot named '{snap}'\n", 1)
    state["vms"][str(uuid_lib.uuid4())] = {"name": new_name, "os": vm["os"], "state": "poweroff", "snapshots": [],
                                           "ga": vm.get("ga", ""), "shared": list(vm.get("shared", []))}
    save(); out("")
if args[0] == "unregistervm":
    if vm["state"] == "running":
        out("Cannot unregister the machine because it is running\n", 1)
    del state["vms"][uuid]; save(); out("")
if args[0] == "sharedfolder":
    vm["shared"].remove(args[args.index("--name") + 1]); save(); out("")
if args[0] == "modifyvm":
    vm.setdefault("modified", []).extend(args[2:]); save(); out("")
if args[0] == "guestproperty":
    out(f"Value: {vm['ga']}\n" if vm.get("ga") and vm["state"] == "running" else "No value set!\n")
if args[0] == "startvm":
    vm["state"] = "running"; save(); out("started\n")
if args[0] == "controlvm":
    cmd = args[2]
    if cmd in ("poweroff", "acpipowerbutton"):
        vm["state"] = "poweroff"
    elif cmd == "savestate":
        vm["state"] = "saved"
    elif cmd == "screenshotpng":
        import struct
        open(args[3], "wb").write(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 1024, 768) + b"\x08\x02\x00\x00\x00")
    save(); out("")
if args[0] == "snapshot":
    if args[2] == "take":
        vm["snapshots"].append(args[3])
    save(); out("")
if args[0] == "guestcontrol":
    pw_index = args.index("--passwordfile") + 1
    entry["password_ok"] = open(args[pw_index]).read() == "test-pass"
    entry["password_file"] = args[pw_index]
    op = args[args.index("--passwordfile") + 2]
    if op == "run":
        out("hello from guest\n", 32 + 3)  # real VBoxManage: guest exit code + 32
    if op == "copyfrom":
        open(args[-1], "w").write("guest file content")
        out("")
    if op == "copyto":
        entry["sent"] = open(args[-2]).read()
        out("")
out("", 0)
'''


@pytest.fixture
def world(tmp_path, monkeypatch):
    stub = tmp_path / "vboxmanage_stub.py"
    stub.write_text(STUB, encoding="utf-8")
    state = {"vms": {
        WIN: {"name": "Win11", "os": "Windows11_64", "state": "poweroff", "snapshots": [], "ga": "7.2.4", "shared": ["code"]},
        LNX: {"name": "Ubuntu", "os": "Ubuntu_64", "state": "running", "snapshots": ["clean"], "ga": ""},
    }}
    state_file, log_file = tmp_path / "state.json", tmp_path / "log.jsonl"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    log_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("VBOX_STUB_STATE", str(state_file))
    monkeypatch.setenv("VBOX_STUB_LOG", str(log_file))
    monkeypatch.setattr(vbox, "vboxmanage", lambda: [sys.executable, str(stub)])

    def run_level(machine):
        vm = json.loads(state_file.read_text(encoding="utf-8"))["vms"][machine["uuid"]]
        return 2 if vm.get("ga") and vm["state"] == "running" else 0

    monkeypatch.setattr(vbox, "additions_run_level", run_level)

    def calls():
        return [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]

    def set_state(uuid, **values):
        data = json.loads(state_file.read_text(encoding="utf-8"))
        data["vms"][uuid].update(values)
        state_file.write_text(json.dumps(data), encoding="utf-8")

    return SimpleNamespace(calls=calls, set_state=set_state, tmp=tmp_path)


# -- seeing ----------------------------------------------------------------------

def test_list_shows_every_vm(world):
    machines = {m["name"]: m for m in vbox.list_vms()}
    assert machines["Win11"]["state"] == "poweroff" and machines["Win11"]["os"] == "Windows11_64"
    assert machines["Ubuntu"]["state"] == "running" and machines["Ubuntu"]["snapshots"] == 1


def test_resolve_by_name_or_uuid_and_reports_unknown_names(world):
    assert vbox.resolve("win11")["uuid"] == WIN and vbox.resolve(LNX)["name"] == "Ubuntu"
    with pytest.raises(vbox.VmError, match="Installed: Win11, Ubuntu"):
        vbox.resolve("Windows")


def test_status_of_a_running_vm_includes_the_guest(world):
    world.set_state(WIN, state="running")
    info = vbox.status(vbox.resolve("Win11"))
    assert info["state"] == "running" and info["guest_additions"] == "7.2.4" and info["memory_mb"] == 8192
    assert info["guest_additions_running"] == "yes (user session)"


def test_a_remembered_version_is_not_proof_guest_additions_run(world, monkeypatch):
    """The version guest property survives a shutdown; only the live run level counts."""
    world.set_state(WIN, state="running")
    monkeypatch.setattr(vbox, "additions_run_level", lambda machine: 0)
    with pytest.raises(vbox.VmError, match="no running Guest Additions"):
        vbox.run(vbox.resolve("Win11"), "Get-Date", "agent", "test-pass")


def test_the_live_run_level_comes_from_the_com_console(monkeypatch):
    module = vbox
    monkeypatch.setattr(module, "_with_console", lambda machine, act: act(SimpleNamespace(Guest=SimpleNamespace(AdditionsRunLevel=3))))
    assert module.additions_run_level({"uuid": "x", "name": "x"}) == 3
    monkeypatch.setattr(module, "_with_console", lambda machine, act: (_ for _ in ()).throw(module.VmError("no COM")))
    assert module.additions_run_level({"uuid": "x", "name": "x"}) == -1


def test_screenshot_saves_a_png_and_reports_its_size(world):
    path, width, height = vbox.screenshot(vbox.resolve("Ubuntu"), str(world.tmp / "shots"))
    assert os.path.isfile(path) and (width, height) == (1024, 768)


def test_screen_and_keyboard_need_a_running_vm(world):
    for action in (lambda m: vbox.screenshot(m, str(world.tmp)), lambda m: vbox.type_text(m, "hi"),
                   lambda m: vbox.press_keys(m, "enter")):
        with pytest.raises(vbox.VmError, match="not running"):
            action(vbox.resolve("Win11"))


# -- power and snapshots ------------------------------------------------------------

def test_start_headless_or_in_a_window(world):
    vbox.start(vbox.resolve("Win11"))
    world.set_state(WIN, state="poweroff")
    vbox.start(vbox.resolve("Win11"), window=True)
    starts = [c["args"] for c in world.calls() if c["args"][0] == "startvm"]
    assert starts == [["startvm", WIN, "--type", "headless"], ["startvm", WIN, "--type", "gui"]]


@pytest.mark.parametrize("how,command", [("shutdown", "acpipowerbutton"), ("poweroff", "poweroff"), ("save", "savestate"),
                                         ("pause", "pause"), ("resume", "resume"), ("reset", "reset")])
def test_power_modes(world, how, command):
    vbox.control(vbox.resolve("Ubuntu"), how)
    assert ["controlvm", LNX, command] in [c["args"] for c in world.calls()]


def test_an_unknown_power_mode_is_refused(world):
    with pytest.raises(vbox.VmError, match="how must be"):
        vbox.control(vbox.resolve("Ubuntu"), "explode")


def test_snapshots_take_and_restore_only_when_stopped(world):
    vbox.snapshot_take(vbox.resolve("Ubuntu"), "before-update")
    assert "before-update" in vbox.status(vbox.resolve("Ubuntu"))["snapshots"]
    with pytest.raises(vbox.VmError, match="power it off or save it"):
        vbox.snapshot_restore(vbox.resolve("Ubuntu"), "clean")
    world.set_state(LNX, state="poweroff")
    assert "restored" in vbox.snapshot_restore(vbox.resolve("Ubuntu"), "clean")


# -- keyboard ---------------------------------------------------------------------------

def test_key_combinations_become_scancodes():
    assert keys.scancodes("ctrl+alt+del") == ["1d", "38", "e0", "53", "e0", "d3", "b8", "9d"]
    assert keys.scancodes("win+r") == ["e0", "5b", "13", "93", "e0", "db"]
    assert keys.scancodes("enter tab") == ["1c", "9c", "0f", "8f"]
    assert keys.scancodes("F12") == ["58", "d8"]


def test_bad_keys_are_explained():
    with pytest.raises(ValueError, match="Unknown key"):
        keys.scancodes("hyper")
    with pytest.raises(ValueError, match="No keys"):
        keys.scancodes("  ")
    with pytest.raises(ValueError, match="use vm type"):
        keys.scancodes("+")


def test_typing_and_keys_go_to_the_vm(world):
    machine = vbox.resolve("Ubuntu")
    vbox.type_text(machine, "hello world")
    vbox.press_keys(machine, "ctrl+alt+del")
    args = [c["args"] for c in world.calls()]
    assert ["controlvm", LNX, "keyboardputstring", "hello world"] in args
    assert ["controlvm", LNX, "keyboardputscancode", "1d", "38", "e0", "53", "e0", "d3", "b8", "9d"] in args


def test_long_key_sequences_are_split(world):
    vbox.press_keys(vbox.resolve("Ubuntu"), " ".join(["a"] * 40))
    chunks = [c["args"] for c in world.calls() if "keyboardputscancode" in c["args"]]
    assert len(chunks) == 2 and sum(len(c) - 3 for c in chunks) == 80


# -- mouse (COM) ---------------------------------------------------------------------------

class _Mouse:
    def __init__(self, absolute=True):
        self.AbsoluteSupported = absolute
        self.events = []

    def PutMouseEventAbsolute(self, x, y, dz, dw, buttons):
        self.events.append((x, y, dz, buttons))


@pytest.fixture
def pointer(world, monkeypatch):
    mouse = _Mouse()
    monkeypatch.setattr(vbox, "_with_console", lambda machine, act: act(SimpleNamespace(Mouse=mouse)))
    return mouse


def test_a_click_moves_presses_and_releases_at_1_based_pixels(world, pointer):
    vbox.mouse(vbox.resolve("Ubuntu"), 100, 200)
    assert pointer.events == [(101, 201, 0, 0), (101, 201, 0, 1), (101, 201, 0, 0)]


def test_double_right_and_none(world, pointer):
    machine = vbox.resolve("Ubuntu")
    vbox.mouse(machine, 10, 10, "double")
    assert [e[3] for e in pointer.events] == [0, 1, 0, 1, 0]
    pointer.events.clear()
    vbox.mouse(machine, 10, 10, "right")
    assert [e[3] for e in pointer.events] == [0, 2, 0]
    pointer.events.clear()
    vbox.mouse(machine, 5, 6, "none")
    assert pointer.events == [(6, 7, 0, 0)]


def test_drag_holds_the_button_to_the_end(world, pointer):
    vbox.mouse(vbox.resolve("Ubuntu"), 0, 0, "drag", to_x=80, to_y=40)
    assert pointer.events[1][3] == 1 and pointer.events[-2][:2] == (81, 41) and pointer.events[-1] == (81, 41, 0, 0)
    with pytest.raises(vbox.VmError, match="to_x"):
        vbox.mouse(vbox.resolve("Ubuntu"), 0, 0, "drag")


def test_scroll_down_is_a_negative_wheel(world, pointer):
    vbox.mouse(vbox.resolve("Ubuntu"), 50, 50, scroll=3)
    assert pointer.events[-1] == (51, 51, -3, 0)


def test_a_guest_without_an_absolute_pointer_is_explained(world, monkeypatch):
    monkeypatch.setattr(vbox, "_with_console", lambda machine, act: act(SimpleNamespace(Mouse=_Mouse(absolute=False))))
    with pytest.raises(vbox.VmError, match="absolute pointer"):
        vbox.mouse(vbox.resolve("Ubuntu"), 1, 1)


# -- inside the guest -------------------------------------------------------------------------

def test_run_in_windows_uses_powershell_and_a_deleted_password_file(world):
    world.set_state(WIN, state="running")
    result = vbox.run(vbox.resolve("Win11"), "Get-Date", "agent", "test-pass")
    assert result["exit_code"] == 3 and "hello from guest" in result["stdout"]
    [call] = [c for c in world.calls() if c["args"][0] == "guestcontrol"]
    args = call["args"]
    assert call["password_ok"] and not os.path.exists(call["password_file"])
    assert "test-pass" not in args  # never on the command line
    assert args[args.index("--exe") + 1].lower().endswith("powershell.exe")
    assert args[-5:] == ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "Get-Date"]


def test_run_in_linux_uses_sh(world):
    world.set_state(LNX, ga="7.2.4")
    vbox.run(vbox.resolve("Ubuntu"), "uname -a", "agent", "test-pass")
    args = [c for c in world.calls() if c["args"][0] == "guestcontrol"][0]["args"]
    assert args[args.index("--exe") + 1] == "/bin/sh" and args[-3:] == ["/bin/sh", "-c", "uname -a"]


def test_inside_the_guest_needs_guest_additions_and_an_account(world):
    with pytest.raises(vbox.VmError, match="no running Guest Additions"):
        vbox.run(vbox.resolve("Ubuntu"), "ls", "agent", "test-pass")
    world.set_state(LNX, ga="7.2.4")
    with pytest.raises(vbox.VmError, match="needs its account"):
        vbox.run(vbox.resolve("Ubuntu"), "ls", "", "")


def test_read_write_and_copy(world):
    world.set_state(WIN, state="running")
    machine = vbox.resolve("Win11")
    assert vbox.read_file(machine, r"C:\notes\a.txt", "agent", "test-pass") == "guest file content"
    vbox.write_file(machine, r"C:\notes\b.txt", "new text", "agent", "test-pass")
    sent = [c for c in world.calls() if "copyto" in c["args"]][0]
    assert sent["sent"] == "new text" and sent["args"][-1] == r"C:\notes\b.txt"


# -- sandbox clones ----------------------------------------------------------------------------

def test_clone_takes_a_golden_snapshot_marks_and_hardens(world):
    message = vbox.clone(vbox.resolve("Win11"))
    assert "Win11-clone-1" in message
    made = vbox.resolve("Win11-clone-1")
    assert vbox.clone_source(made) == WIN
    calls = [c["args"] for c in world.calls()]
    assert ["snapshot", WIN, "take", "a0w-golden", "--description", "Base for A0W sandbox clones"] in calls
    assert ["clonevm", WIN, "--snapshot", "a0w-golden", "--options", "Link", "--name", "Win11-clone-1", "--register"] in calls
    modify = next(c for c in calls if c[0] == "modifyvm" and c[1] == made["uuid"])
    assert ["--clipboard-mode", "disabled", "--drag-and-drop", "disabled", "--nat-localhostreachable1", "off"] == modify[2:]
    assert ["sharedfolder", "remove", made["uuid"], "--name", "code"] in calls


def test_clone_uses_the_current_snapshot_and_counts_names(world):
    vbox.clone(vbox.resolve("Ubuntu"))
    vbox.clone(vbox.resolve("Ubuntu"))
    names = [m["name"] for m in vbox.list_vms()]
    assert "Ubuntu-clone-1" in names and "Ubuntu-clone-2" in names
    assert not [c for c in world.calls() if c["args"][:3] == ["snapshot", LNX, "take"]]


def test_a_clone_of_a_clone_is_refused_and_so_is_deleting_a_non_clone(world):
    vbox.clone(vbox.resolve("Win11"))
    with pytest.raises(vbox.VmError, match="itself a clone"):
        vbox.clone(vbox.resolve("Win11-clone-1"))
    with pytest.raises(vbox.VmError, match="not an A0W-made clone"):
        vbox.delete_clone(vbox.resolve("Win11"))
    with pytest.raises(vbox.VmError, match="already exists"):
        vbox.clone(vbox.resolve("Win11"), "ubuntu")


def test_delete_clone_powers_off_first(world):
    vbox.clone(vbox.resolve("Win11"))
    made = vbox.resolve("Win11-clone-1")
    world.set_state(made["uuid"], state="running")
    vbox.delete_clone(made)
    calls = [c["args"] for c in world.calls()]
    assert ["controlvm", made["uuid"], "poweroff"] in calls
    assert ["unregistervm", made["uuid"], "--delete"] in calls
    assert "Win11-clone-1" not in [m["name"] for m in vbox.list_vms()]


def test_reset_clone_replaces_it_with_a_fresh_one(world):
    vbox.clone(vbox.resolve("Ubuntu"))
    old = vbox.resolve("Ubuntu-clone-1")
    message = vbox.reset_clone(old)
    assert "fresh clone" in message
    fresh = vbox.resolve("Ubuntu-clone-1")
    assert fresh["uuid"] != old["uuid"] and vbox.clone_source(fresh) == LNX


# -- the tool -----------------------------------------------------------------------------

def _tool(secrets=None, monkeypatch=None):
    from plugins._vm.tools.vm import Vm

    agent = SimpleNamespace(context=SimpleNamespace(id="c1"), agent_name="A0")
    tool = Vm(agent=agent, name="vm", method=None, args={}, message="", loop_data=None)
    if monkeypatch is not None:
        import helpers.secrets as secrets_module

        monkeypatch.setattr(secrets_module, "get_secrets_manager",
                            lambda context=None: SimpleNamespace(load_secrets=lambda: dict(secrets or {})))
    return tool


def test_the_tool_lists_and_reports_errors_as_repairable(world, monkeypatch):
    from helpers.errors import RepairableException

    tool = _tool(monkeypatch=monkeypatch)
    listing = asyncio.run(tool.execute(action="list")).message
    assert "Win11 (Windows11_64): poweroff" in listing
    with pytest.raises(RepairableException, match=r"\[vm\] No VM called"):
        asyncio.run(tool.execute(action="status", vm="nope"))


def test_credentials_come_from_args_then_per_vm_then_default_secrets(world, monkeypatch):
    machine = vbox.resolve("Win11")
    tool = _tool({"VM_USER": "default", "VM_PASSWORD": "d-pass", "VM_WIN11_USER": "winuser", "VM_WIN11_PASSWORD": "w-pass"},
                 monkeypatch)
    assert tool._credentials(machine, {}) == ("winuser", "w-pass")
    assert tool._credentials(vbox.resolve("Ubuntu"), {}) == ("default", "d-pass")
    assert tool._credentials(machine, {"user": "u", "password": "p"}) == ("u", "p")


def test_the_log_never_shows_a_password(world, monkeypatch):
    tool = _tool(monkeypatch=monkeypatch)
    tool.args = {"action": "run", "vm": "Win11", "password": "test-pass"}
    seen = {}
    tool.agent.context.log = SimpleNamespace(log=lambda **kw: seen.update(kw))
    tool.get_log_object()
    assert seen["kvps"]["password"] == "***"


def test_copy_out_defaults_to_the_workdir(world, monkeypatch):
    import plugins._vm.tools.vm as vm_module

    world.set_state(WIN, state="running")
    monkeypatch.setattr(vm_module, "_workdir", lambda: str(world.tmp / "work"))
    tool = _tool({"VM_USER": "agent", "VM_PASSWORD": "test-pass"}, monkeypatch)
    message = asyncio.run(tool.execute(action="copy_out", vm="Win11", guest_path=r"C:\logs\run.log")).message
    expected = world.tmp / "work" / "vm-files" / "Win11" / "run.log"
    assert str(expected) in message and expected.read_text(encoding="utf-8") == "guest file content"


def test_looking_is_a_read_and_acting_is_execute():
    from plugins._permissions.helpers import rules

    for action in ("list", "status", "snapshots", "screenshot", "clones"):
        assert rules.classify("vm", {"action": action}) == "read", action
    for action in ("start", "stop", "restore", "type", "keys", "mouse", "run", "write", "copy_in", "copy_out",
                   "clone", "delete_clone", "reset_clone"):
        assert rules.classify("vm", {"action": action}) == "execute", action


def test_the_tool_lists_clones(world, monkeypatch):
    tool = _tool(monkeypatch=monkeypatch)
    assert "No A0W-made clones" in asyncio.run(tool.execute(action="clones")).message
    asyncio.run(tool.execute(action="clone", vm="Win11"))
    listing = asyncio.run(tool.execute(action="clones")).message
    assert "- Win11-clone-1 (clone of Win11): poweroff" in listing


# -- the prompt --------------------------------------------------------------------------------

def _prompt_ext(monkeypatch, installed=True, hidden=False):
    import importlib

    module = importlib.import_module("plugins._vm.extensions.python._functions._11_tools_prompt.build_prompt.end._72_include_vm_tool")
    monkeypatch.setattr(vbox, "installed", lambda: installed)
    from plugins._capabilities.helpers import policy

    monkeypatch.setattr(policy, "tool_hidden", lambda agent, tool: hidden)
    agent = SimpleNamespace(read_prompt=lambda name: (ROOT / "plugins/_vm/prompts" / name).read_text(encoding="utf-8"))
    data = {"result": "### response\n..."}
    module.IncludeVmTool(agent=agent).execute(data=data)
    return data["result"]


def test_the_tool_is_described_only_where_virtualbox_is_installed(monkeypatch):
    assert '"tool_name": "vm"' in _prompt_ext(monkeypatch)
    assert "### vm" not in _prompt_ext(monkeypatch, installed=False)
    assert "### vm" not in _prompt_ext(monkeypatch, hidden=True)

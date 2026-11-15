"""Control of VirtualBox virtual machines for the `vm` tool.

Two routes, each used where it is strongest:
- `VBoxManage` (the documented command line) for everything it does well:
  listing machines, power, snapshots, screenshots, keyboard input, and running
  programs and copying files inside the guest (Guest Additions).
- VirtualBox's COM API (through pywin32) for what VBoxManage cannot do:
  the mouse (absolute pointer moves, clicks, drags, scroll) and asking whether
  the guest accepts an absolute pointer.

Machines are addressed by name or UUID; a name the model types is resolved to
a UUID first, so a command never runs against the wrong machine by a typo.
Guest passwords never go on a command line (other processes can read command
lines): VBoxManage gets them through `--passwordfile`, a temporary file that
is deleted right after.

The tool never changes a machine's settings (memory, network, shared folders,
clipboard): those stay the owner's. The one exception is a sandbox clone the
tool itself made: cloning hardens it (host loopback, shared folders, clipboard
and drag-and-drop all off), and only such clones may be deleted.
"""

from __future__ import annotations

import ntpath
import os
import posixpath
import re
import shutil
import struct
import subprocess
import tempfile
import time
from pathlib import Path

from plugins._vm.helpers import keys as key_codes

CREATE_NO_WINDOW = 0x08000000
DEFAULT_TIMEOUT = 60
RUN_TIMEOUT = 120
MAX_OUTPUT_CHARS = 20000
MAX_READ_BYTES = 1024 * 1024
RUNNING_STATES = {"running", "paused", "stuck", "teleporting", "livesnapshotting"}
# COM: LockType_Shared, MouseButtonState bits
LOCK_SHARED = 1
BUTTONS = {"left": 0x01, "right": 0x02, "middle": 0x04}


class VmError(Exception):
    pass


# ------------------------------------------------------------------ VBoxManage

def vboxmanage() -> list[str]:
    """The VBoxManage command, or raise when VirtualBox is not installed."""
    found = shutil.which("VBoxManage")
    if found:
        return [found]
    for base in (os.environ.get("VBOX_MSI_INSTALL_PATH", ""), os.environ.get("VBOX_INSTALL_PATH", ""),
                 r"C:\Program Files\Oracle\VirtualBox"):
        if base:
            candidate = Path(base) / "VBoxManage.exe"
            if candidate.is_file():
                return [str(candidate)]
    raise VmError("VirtualBox is not installed (VBoxManage was not found).")


def installed() -> bool:
    try:
        vboxmanage()
        return True
    except VmError:
        return False


def _run(args: list[str], timeout: float = DEFAULT_TIMEOUT, check: bool = True) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run([*vboxmanage(), *args], capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout, creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        raise VmError(f"VBoxManage did not finish within {int(timeout)} s.") from exc
    if check and result.returncode != 0:
        raise VmError(_clean_error(result.stderr or result.stdout) or f"VBoxManage failed (exit {result.returncode}).")
    return result


def _clean_error(text: str) -> str:
    lines = [line.replace("VBoxManage.exe: error: ", "").replace("VBoxManage: error: ", "").strip()
             for line in (text or "").splitlines()]
    useful = [line for line in lines if line and not line.startswith(("Details:", "Context:"))]
    return " ".join(useful[:3])[:500]


def parse_machinereadable(text: str) -> dict[str, str]:
    info: dict[str, str] = {}
    for line in (text or "").splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        info[key.strip().strip('"')] = value.strip().strip('"')
    return info


def list_vms() -> list[dict]:
    """Every registered machine: name, uuid, state, os."""
    running = {m.group(2) for m in re.finditer(r'^"(.*)" \{([0-9a-fA-F-]+)\}$', _run(["list", "runningvms"]).stdout, re.M)}
    machines = []
    for match in re.finditer(r'^"(.*)" \{([0-9a-fA-F-]+)\}$', _run(["list", "vms"]).stdout, re.M):
        name, uuid = match.group(1), match.group(2)
        try:
            info = parse_machinereadable(_run(["showvminfo", uuid, "--machinereadable"]).stdout)
        except VmError:
            info = {}
        machines.append({"name": name, "uuid": uuid, "state": info.get("VMState", "running" if uuid in running else "unknown"),
                         "os": info.get("ostype", ""), "snapshots": sum(1 for k in info if k.startswith("SnapshotName"))})
    return machines


def resolve(vm: str) -> dict:
    """The machine named (exactly, ignoring case) or with that UUID."""
    wanted = str(vm or "").strip()
    if not wanted:
        raise VmError("Say which VM (its name or UUID); `vm list` shows them.")
    machines = list_vms()
    for machine in machines:
        if wanted.lower() in (machine["name"].lower(), machine["uuid"].lower()):
            return machine
    names = ", ".join(m["name"] for m in machines) or "none"
    raise VmError(f"No VM called '{wanted}'. Installed: {names}.")


def is_windows(machine_or_info: dict) -> bool:
    return str(machine_or_info.get("os") or machine_or_info.get("ostype") or "").lower().startswith("windows")


def status(machine: dict) -> dict:
    info = parse_machinereadable(_run(["showvminfo", machine["uuid"], "--machinereadable"]).stdout)
    state = info.get("VMState", machine.get("state", ""))
    result = {
        "name": machine["name"], "uuid": machine["uuid"], "state": state, "os": info.get("ostype", ""),
        "memory_mb": _as_int(info.get("memory")), "cpus": _as_int(info.get("cpus")), "firmware": info.get("firmware", ""),
        "network": info.get("nic1", ""), "snapshots": [v for k, v in info.items() if k.startswith("SnapshotName")],
        "current_snapshot": info.get("CurrentSnapshotName", ""),
    }
    if state in RUNNING_STATES:
        result["guest_additions"] = guest_property(machine, "/VirtualBox/GuestAdd/Version")
        result["guest_additions_running"] = RUN_LEVELS.get(additions_run_level(machine), "unknown")
        result["guest_os"] = guest_property(machine, "/VirtualBox/GuestInfo/OS/Product")
        result["logged_in_users"] = guest_property(machine, "/VirtualBox/GuestInfo/OS/LoggedInUsersList")
    return result


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def guest_property(machine: dict, name: str) -> str:
    out = _run(["guestproperty", "get", machine["uuid"], name], check=False).stdout.strip()
    return out[len("Value: "):] if out.startswith("Value: ") else ""


def _require_running(machine: dict) -> None:
    state = parse_machinereadable(_run(["showvminfo", machine["uuid"], "--machinereadable"]).stdout).get("VMState", "")
    if state not in RUNNING_STATES:
        raise VmError(f"'{machine['name']}' is not running (state: {state or 'unknown'}). Start it first with `vm start`.")


# ------------------------------------------------------------------ power and snapshots

def start(machine: dict, window: bool = False) -> str:
    _run(["startvm", machine["uuid"], "--type", "gui" if window else "headless"], timeout=120)
    return f"'{machine['name']}' is starting" + (" in a window." if window else " without a window (headless).")


STOP_MODES = {"shutdown": "acpipowerbutton", "poweroff": "poweroff", "save": "savestate",
              "pause": "pause", "resume": "resume", "reset": "reset"}


def control(machine: dict, how: str) -> str:
    command = STOP_MODES.get(how)
    if not command:
        raise VmError("how must be shutdown, poweroff, save, pause, resume or reset.")
    _run(["controlvm", machine["uuid"], command], timeout=120)
    notes = {"shutdown": "asked the guest to shut down (it may take a while, or be ignored at a login screen)",
             "poweroff": "powered off at once (like pulling the plug; unsaved work in the guest is lost)",
             "save": "saved its state and stopped it", "pause": "paused it", "resume": "resumed it",
             "reset": "reset it (a hard restart)"}
    return f"'{machine['name']}': {notes[how]}."


def snapshot_take(machine: dict, name: str, description: str = "") -> str:
    if not str(name or "").strip():
        raise VmError("A snapshot needs a name.")
    args = ["snapshot", machine["uuid"], "take", name]
    if description:
        args += ["--description", description]
    _run(args, timeout=600)
    return f"Snapshot '{name}' of '{machine['name']}' taken."


def snapshot_restore(machine: dict, name: str) -> str:
    state = status(machine)["state"]
    if state in RUNNING_STATES:
        raise VmError(f"'{machine['name']}' is {state}; power it off or save it before restoring a snapshot.")
    _run(["snapshot", machine["uuid"], "restore", name], timeout=600)
    return f"'{machine['name']}' restored to snapshot '{name}'. Its changes since then are gone."


# ------------------------------------------------------------------ sandbox clones

CLONE_MARK = "A0W/clone-of"
GOLDEN_SNAPSHOT = "a0w-golden"


def extradata(machine: dict, key: str) -> str:
    out = _run(["getextradata", machine["uuid"], key], check=False).stdout.strip()
    return out[len("Value: "):] if out.startswith("Value: ") else ""


def clone_source(machine: dict) -> str:
    """The golden VM's UUID when `machine` is an A0W-made clone, else ""."""
    return extradata(machine, CLONE_MARK)


def list_clones() -> list[dict]:
    machines = list_vms()
    names = {m["uuid"]: m["name"] for m in machines}
    clones = []
    for machine in machines:
        source = clone_source(machine)
        if source:
            machine["golden"] = names.get(source, source)
            clones.append(machine)
    return clones


def clone(golden: dict, name: str = "") -> str:
    """A linked clone of `golden`, hardened for sandbox work. Linked clones
    build on a snapshot: the golden VM's current one, or one taken now."""
    if clone_source(golden):
        raise VmError(f"'{golden['name']}' is itself a clone; clone the golden VM instead.")
    info = parse_machinereadable(_run(["showvminfo", golden["uuid"], "--machinereadable"]).stdout)
    snapshot = info.get("CurrentSnapshotName", "")
    if not snapshot:
        snapshot_take(golden, GOLDEN_SNAPSHOT, "Base for A0W sandbox clones")
        snapshot = GOLDEN_SNAPSHOT
    taken = {m["name"].lower() for m in list_vms()}
    name = str(name or "").strip()
    if not name:
        number = 1
        while f"{golden['name']}-clone-{number}".lower() in taken:
            number += 1
        name = f"{golden['name']}-clone-{number}"
    elif name.lower() in taken:
        raise VmError(f"A VM called '{name}' already exists.")
    _run(["clonevm", golden["uuid"], "--snapshot", snapshot, "--options", "Link", "--name", name, "--register"],
         timeout=600)
    machine = resolve(name)
    _run(["setextradata", machine["uuid"], CLONE_MARK, golden["uuid"]])
    _harden(machine)
    return (f"Cloned '{golden['name']}' (snapshot '{snapshot}') to '{name}': a sandbox with no host loopback, "
            "shared folders or clipboard. A broken clone is cheap: `vm reset_clone` replaces it with a fresh one.")


def _harden(machine: dict) -> None:
    """Cut the host-facing surfaces a sandbox must not keep: reaching the
    host's own services through NAT, the shared clipboard, drag and drop,
    and every shared folder."""
    info = parse_machinereadable(_run(["showvminfo", machine["uuid"], "--machinereadable"]).stdout)
    args = ["modifyvm", machine["uuid"], "--clipboard-mode", "disabled", "--drag-and-drop", "disabled"]
    for key, value in info.items():
        if re.fullmatch(r"nic\d+", key) and value == "nat":
            args += [f"--nat-localhostreachable{key[3:]}", "off"]
    _run(args)
    for key, value in info.items():
        if key.startswith("SharedFolderNameMachineMapping"):
            _run(["sharedfolder", "remove", machine["uuid"], "--name", value])


def delete_clone(machine: dict) -> str:
    if not clone_source(machine):
        raise VmError(f"'{machine['name']}' is not an A0W-made clone, so `vm` will not delete it.")
    if status(machine)["state"] in RUNNING_STATES:
        _run(["controlvm", machine["uuid"], "poweroff"], timeout=120)
        for _ in range(40):
            if status(machine)["state"] not in RUNNING_STATES:
                break
            time.sleep(0.5)
    _run(["unregistervm", machine["uuid"], "--delete"], timeout=600)
    return f"Deleted clone '{machine['name']}' and its disk."


def reset_clone(machine: dict) -> str:
    source = clone_source(machine)
    if not source:
        raise VmError(f"'{machine['name']}' is not an A0W-made clone; `vm restore` resets ordinary VMs to a snapshot.")
    golden = resolve(source)
    name = machine["name"]
    delete_clone(machine)
    clone(golden, name)
    return f"Reset '{name}': a fresh clone of '{golden['name']}' replaced it (the old one is deleted)."


# ------------------------------------------------------------------ screen and keyboard

def png_size(path: str) -> tuple[int, int]:
    with open(path, "rb") as fh:
        head = fh.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return 0, 0
    return struct.unpack(">II", head[16:24])


def screenshot(machine: dict, folder: str) -> tuple[str, int, int]:
    _require_running(machine)
    os.makedirs(folder, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", machine["name"]).strip("-") or "vm"
    path = os.path.join(folder, f"{slug}-{int(time.time() * 1000)}.png")
    _run(["controlvm", machine["uuid"], "screenshotpng", path], timeout=60)
    width, height = png_size(path)
    return path, width, height


def type_text(machine: dict, text: str) -> str:
    _require_running(machine)
    if not text:
        raise VmError("Nothing to type.")
    _run(["controlvm", machine["uuid"], "keyboardputstring", text], timeout=120)
    return f"Typed {len(text)} characters into '{machine['name']}'."


def press_keys(machine: dict, spec: str) -> str:
    _require_running(machine)
    try:
        codes = key_codes.scancodes(spec)
    except ValueError as exc:
        raise VmError(str(exc)) from exc
    for chunk in (codes[i:i + 64] for i in range(0, len(codes), 64)):  # keep command lines short
        _run(["controlvm", machine["uuid"], "keyboardputscancode", *chunk], timeout=60)
    return f"Pressed {spec} in '{machine['name']}'."


# ------------------------------------------------------------------ mouse (COM)

def _with_console(machine: dict, action):
    """Run `action(console)` with a shared lock on a running machine."""
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise VmError("Mouse control needs pywin32 (it is part of A0W's Windows install).") from exc
    pythoncom.CoInitialize()
    session = None
    try:
        vbox = win32com.client.Dispatch("VirtualBox.VirtualBox")
        target = vbox.FindMachine(machine["uuid"])
        session = win32com.client.Dispatch("VirtualBox.Session")
        target.LockMachine(session, LOCK_SHARED)
        return action(session.Console)
    except VmError:
        raise
    except Exception as exc:
        raise VmError(f"VirtualBox refused the mouse action: {exc}") from exc
    finally:
        if session is not None:
            try:
                session.UnlockMachine()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def mouse(machine: dict, x: int, y: int, click: str = "left", to_x: int | None = None, to_y: int | None = None,
          scroll: int = 0) -> str:
    """Move to (x, y) in screen pixels, then click/double-click/right-click,
    drag to (to_x, to_y), or scroll (positive = down)."""
    _require_running(machine)
    click = str(click or "left").lower()
    if click not in ("left", "right", "middle", "double", "none", "drag"):
        raise VmError("click must be left, right, middle, double, drag or none.")

    def act(console):
        pointer = console.Mouse
        if not pointer.AbsoluteSupported:
            raise VmError("This VM's guest does not accept an absolute pointer yet (Guest Additions or a USB tablet "
                          "are needed). Use the keyboard (vm keys) instead.")
        # VirtualBox's absolute coordinates are 1-based pixels.
        px, py = int(x) + 1, int(y) + 1
        pointer.PutMouseEventAbsolute(px, py, 0, 0, 0)
        if scroll:
            pointer.PutMouseEventAbsolute(px, py, -int(scroll), 0, 0)  # VirtualBox: positive dz = wheel up
            return f"scrolled {'down' if scroll > 0 else 'up'} {abs(int(scroll))} at ({x}, {y})"
        if click == "none":
            return f"moved to ({x}, {y})"
        if click == "drag":
            if to_x is None or to_y is None:
                raise VmError("A drag needs to_x and to_y.")
            pointer.PutMouseEventAbsolute(px, py, 0, 0, BUTTONS["left"])
            steps = 8
            for i in range(1, steps + 1):
                pointer.PutMouseEventAbsolute(px + (int(to_x) + 1 - px) * i // steps,
                                              py + (int(to_y) + 1 - py) * i // steps, 0, 0, BUTTONS["left"])
                time.sleep(0.02)
            pointer.PutMouseEventAbsolute(int(to_x) + 1, int(to_y) + 1, 0, 0, 0)
            return f"dragged from ({x}, {y}) to ({to_x}, {to_y})"
        button = BUTTONS["left" if click == "double" else click]
        for _ in range(2 if click == "double" else 1):
            pointer.PutMouseEventAbsolute(px, py, 0, 0, button)
            time.sleep(0.03)
            pointer.PutMouseEventAbsolute(px, py, 0, 0, 0)
            time.sleep(0.06)
        return f"{click}-clicked at ({x}, {y})"

    return f"'{machine['name']}': " + _with_console(machine, act) + "."


# ------------------------------------------------------------------ inside the guest (Guest Additions)

class _PasswordFile:
    """A temporary file holding the guest password, deleted on exit."""

    def __init__(self, password: str):
        self.password = password
        self.path = ""

    def __enter__(self) -> str:
        handle, self.path = tempfile.mkstemp(prefix="a0vm-", suffix=".txt")
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(self.password)
        return self.path

    def __exit__(self, *exc):
        try:
            os.remove(self.path)
        except OSError:
            pass
        return False


def _guest_args(machine: dict, user: str, password_file: str) -> list[str]:
    return ["guestcontrol", machine["uuid"], "--username", user, "--passwordfile", password_file]


RUN_LEVELS = {0: "no", 1: "system services only", 2: "yes (user session)", 3: "yes (desktop)"}


def additions_run_level(machine: dict) -> int:
    """How far the guest's Guest Additions are running right now (0 = not at
    all, 1 = system, 2 = userland, 3 = desktop). The version guest property
    is remembered while a VM is off, so it cannot tell this; -1 = unknown."""
    try:
        return int(_with_console(machine, lambda console: console.Guest.AdditionsRunLevel))
    except Exception:
        return -1


def _need_guest(machine: dict, user: str, password: str) -> None:
    _require_running(machine)
    level = additions_run_level(machine)
    if level == 0 or (level < 0 and not guest_property(machine, "/VirtualBox/GuestAdd/Version")):
        raise VmError(f"'{machine['name']}' has no running Guest Additions, so programs cannot be started inside it. "
                      "Use the screen, keyboard and mouse actions instead, or install Guest Additions in the guest.")
    if not user or not password:
        raise VmError("Running programs or copying files inside a guest needs its account: pass user and "
                      "password as §§secret(...) placeholders, or set VM_USER / VM_PASSWORD in Secrets.")


def shell_for(machine: dict, shell: str = "auto") -> tuple[str, list[str]]:
    shell = str(shell or "auto").lower()
    if shell == "auto":
        shell = "powershell" if is_windows(machine) else "sh"
    if shell == "powershell":
        return r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe", ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"]
    if shell == "cmd":
        return r"C:\Windows\System32\cmd.exe", ["cmd.exe", "/c"]
    if shell in ("sh", "bash"):
        exe = "/bin/bash" if shell == "bash" else "/bin/sh"
        return exe, [exe, "-c"]
    raise VmError("shell must be auto, powershell, cmd, sh or bash.")


def run(machine: dict, command: str, user: str, password: str, shell: str = "auto", timeout: int = RUN_TIMEOUT) -> dict:
    """Run `command` inside the guest; returns exit code, stdout, stderr."""
    if not str(command or "").strip():
        raise VmError("Nothing to run.")
    _need_guest(machine, user, password)
    exe, argv = shell_for(machine, shell)
    with _PasswordFile(password) as pwfile:
        result = _run([*_guest_args(machine, user, pwfile), "run", "--exe", exe, "--timeout", str(int(timeout) * 1000),
                       "--wait-stdout", "--wait-stderr", "--", *argv, command], timeout=int(timeout) + 30, check=False)
    # VBoxManage exits with the guest process's exit code + 32 when that is not 0 (capped around 126, so
    # guest codes of about 94 and above all read as 94); small values are VBoxManage's own errors.
    code = result.returncode - 32 if result.returncode > 32 else result.returncode
    return {"exit_code": code, "stdout": _cap(result.stdout), "stderr": _cap(_clean_guest_stderr(result.stderr))}


def _clean_guest_stderr(text: str) -> str:
    return "\n".join(line for line in (text or "").splitlines() if not line.startswith("VBoxManage.exe: warning:"))


def _cap(text: str) -> str:
    text = text or ""
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n... ({len(text) - MAX_OUTPUT_CHARS} more characters)"


def _guest_path(machine: dict):
    return ntpath if is_windows(machine) else posixpath


def copy_from(machine: dict, guest_path: str, host_path: str, user: str, password: str) -> str:
    _need_guest(machine, user, password)
    os.makedirs(os.path.dirname(os.path.abspath(host_path)) or ".", exist_ok=True)
    with _PasswordFile(password) as pwfile:
        _run([*_guest_args(machine, user, pwfile), "copyfrom", guest_path, host_path], timeout=600)
    return host_path


def copy_to(machine: dict, host_path: str, guest_path: str, user: str, password: str) -> str:
    _need_guest(machine, user, password)
    if not os.path.isfile(host_path):
        raise VmError(f"{host_path} does not exist on this PC.")
    with _PasswordFile(password) as pwfile:
        _run([*_guest_args(machine, user, pwfile), "copyto", host_path, guest_path], timeout=600)
    return guest_path


def read_file(machine: dict, guest_path: str, user: str, password: str) -> str:
    with tempfile.TemporaryDirectory(prefix="a0vm-read-") as tmp:
        local = os.path.join(tmp, _guest_path(machine).basename(guest_path) or "file")
        copy_from(machine, guest_path, local, user, password)
        size = os.path.getsize(local)
        if size > MAX_READ_BYTES:
            raise VmError(f"{guest_path} is {size} bytes; use `vm copy_out` for files over {MAX_READ_BYTES} bytes.")
        with open(local, "rb") as fh:
            return fh.read().decode("utf-8", errors="replace")


def write_file(machine: dict, guest_path: str, content: str, user: str, password: str) -> str:
    with tempfile.TemporaryDirectory(prefix="a0vm-write-") as tmp:
        local = os.path.join(tmp, _guest_path(machine).basename(guest_path) or "file")
        with open(local, "w", encoding="utf-8", newline="") as fh:
            fh.write(content or "")
        copy_to(machine, local, guest_path, user, password)
    return f"Wrote {len(content or '')} characters to {guest_path} in '{machine['name']}'."

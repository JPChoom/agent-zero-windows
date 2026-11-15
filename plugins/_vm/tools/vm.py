import asyncio
import json
import os
import re

from helpers import files
from helpers.errors import RepairableException
from helpers.tool import Response, Tool
from plugins._vm.helpers import vbox

READ_ACTIONS = {"list", "status", "snapshots", "screenshot"}


class Vm(Tool):
    """Full control of installed VirtualBox VMs (plugins/_vm/helpers/vbox.py)."""

    async def execute(self, action: str = "", vm: str = "", **kwargs):
        action = str(action or self.method or "list").strip().lower()
        try:
            message = await asyncio.to_thread(self._dispatch, action, vm, kwargs)
        except vbox.VmError as exc:
            raise RepairableException(f"[vm] {exc}") from exc
        return Response(message=message, break_loop=False)

    # ------------------------------------------------------------------ dispatch (runs in a worker thread)

    def _dispatch(self, action: str, vm: str, args: dict) -> str:
        if action == "list":
            machines = vbox.list_vms()
            if not machines:
                return "No VirtualBox VMs are installed."
            return "\n".join(f"- {m['name']} ({m['os'] or 'unknown OS'}): {m['state']}, {m['snapshots']} snapshot(s)"
                             for m in machines)
        if action == "clones":
            clones = vbox.list_clones()
            if not clones:
                return "No A0W-made clones exist. `vm clone` makes one from a golden VM."
            return "\n".join(f"- {c['name']} (clone of {c['golden']}): {c['state']}" for c in clones)
        machine = vbox.resolve(vm)
        if action == "status":
            return json.dumps(vbox.status(machine), indent=2)
        if action == "start":
            return vbox.start(machine, window=_flag(args.get("window")))
        if action == "stop":
            return vbox.control(machine, str(args.get("how") or "shutdown").lower())
        if action in ("pause", "resume", "reset", "poweroff", "save", "shutdown"):
            return vbox.control(machine, action)
        if action == "snapshots":
            snaps = vbox.status(machine)["snapshots"]
            return "Snapshots: " + (", ".join(snaps) if snaps else "none")
        if action == "snapshot":
            return vbox.snapshot_take(machine, str(args.get("name") or ""), str(args.get("description") or ""))
        if action == "restore":
            return vbox.snapshot_restore(machine, str(args.get("name") or ""))
        if action == "clone":
            return vbox.clone(machine, str(args.get("name") or ""))
        if action == "delete_clone":
            return vbox.delete_clone(machine)
        if action == "reset_clone":
            return vbox.reset_clone(machine)
        if action == "screenshot":
            path, width, height = vbox.screenshot(machine, files.get_abs_path("tmp", "vm"))
            return (f"Screenshot of '{machine['name']}' ({width}x{height} pixels) saved to {path} - load it with "
                    "vision_load to look at it. Mouse coordinates use these pixels, from the top-left corner.")
        if action == "type":
            return vbox.type_text(machine, str(args.get("text") or ""))
        if action == "keys":
            return vbox.press_keys(machine, str(args.get("keys") or ""))
        if action == "mouse":
            return vbox.mouse(machine, _int(args.get("x"), "x"), _int(args.get("y"), "y"), str(args.get("click") or "left"),
                              _opt_int(args.get("to_x")), _opt_int(args.get("to_y")), _opt_int(args.get("scroll")) or 0)
        user, password = self._credentials(machine, args)
        if action == "run":
            result = vbox.run(machine, str(args.get("command") or ""), user, password,
                              str(args.get("shell") or "auto"), _opt_int(args.get("timeout")) or vbox.RUN_TIMEOUT)
            parts = [f"exit code {result['exit_code']}"]
            if result["stdout"]:
                parts.append("stdout:\n" + result["stdout"])
            if result["stderr"]:
                parts.append("stderr:\n" + result["stderr"])
            return "\n".join(parts)
        if action == "read":
            return vbox.read_file(machine, _req(args, "path"), user, password)
        if action == "write":
            return vbox.write_file(machine, _req(args, "path"), str(args.get("content") or ""), user, password)
        if action == "copy_in":
            return "Copied to " + vbox.copy_to(machine, _host_path(_req(args, "host_path")), _req(args, "guest_path"), user, password)
        if action == "copy_out":
            guest = _req(args, "guest_path")
            host = args.get("host_path") or os.path.join(_workdir(), "vm-files", _slug(machine["name"]),
                                                          re.split(r"[\\/]", guest)[-1] or "file")
            return "Copied to " + vbox.copy_from(machine, guest, _host_path(str(host)), user, password)
        raise vbox.VmError("action must be list, status, start, stop, pause, resume, reset, snapshots, snapshot, restore, "
                           "screenshot, type, keys, mouse, run, read, write, copy_in, copy_out, clone, clones, "
                           "reset_clone or delete_clone.")

    def _credentials(self, machine: dict, args: dict) -> tuple[str, str]:
        """The guest account: tool args (passwords arrive as §§secret(...)
        placeholders, filled in before the tool runs), else Secrets:
        VM_<NAME>_USER / VM_<NAME>_PASSWORD, then VM_USER / VM_PASSWORD."""
        user, password = str(args.get("user") or ""), str(args.get("password") or "")
        if user and password:
            return user, password
        try:
            from helpers.secrets import get_secrets_manager

            secrets = get_secrets_manager(self.agent.context).load_secrets()
        except Exception:
            secrets = {}
        slug = _slug(machine["name"]).upper().replace("-", "_")
        user = user or secrets.get(f"VM_{slug}_USER") or secrets.get("VM_USER", "")
        password = password or secrets.get(f"VM_{slug}_PASSWORD") or secrets.get("VM_PASSWORD", "")
        return user, password

    def get_log_object(self):
        args = dict(self.args or {})
        if args.get("password"):
            args["password"] = "***"
        return self.agent.context.log.log(type="tool", heading=f"icon://computer {self.agent.agent_name}: Using tool 'vm'",
                                          content="", kvps=args, _tool_name=self.name)


def _flag(value) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes", "on")


def _int(value, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise vbox.VmError(f"{name} must be a whole number of pixels.")


def _opt_int(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _req(args: dict, key: str) -> str:
    value = str(args.get(key) or "").strip()
    if not value:
        raise vbox.VmError(f"This action needs {key}.")
    return value


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-") or "vm"


def _workdir() -> str:
    try:
        from plugins._text_editor.helpers.file_ops import get_workdir_root

        return str(get_workdir_root())
    except Exception:
        return files.get_abs_path("usr", "workdir")


def _host_path(path: str) -> str:
    native = files.native_path(path) if hasattr(files, "native_path") else path
    return native if os.path.isabs(native) else os.path.join(_workdir(), native)

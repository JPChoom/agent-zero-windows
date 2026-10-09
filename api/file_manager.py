import asyncio
import os
import subprocess

from helpers import access_control
from helpers import file_access as fa
from helpers import file_manager as fm
from helpers.api import ApiHandler, Request, Response

AUDITED = {"mkdir", "new_file", "rename", "delete", "copy", "move", "write_text"}


def caller(request) -> tuple[bool, str]:
    """(is_remote, who) for policy and audit."""
    remote_addr = getattr(request, "remote_addr", None)
    headers = getattr(request, "headers", {}) or {}
    if access_control.is_local_request(remote_addr, headers):
        return False, "local"
    return True, access_control.client_ip(remote_addr, headers) or "?"


class FileManager(ApiHandler):
    """The Windows File Browser (webui/components/modals/file-browser).

    Paths are absolute Windows paths. Every action is checked against the
    caller's policy (helpers/file_access.py): local sessions use the File
    Browser access mode, remote sessions its remote cap.

    actions: places | locate {path} | list {path, show_hidden} | mkdir {path, name} |
      new_file {path, name} | rename {path, name} | delete {paths, permanent} |
      copy {paths, dest} | move {paths, dest} | read_text {path} |
      write_text {path, content, encoding, expected_modified, newline} |
      reveal {path} (opens Explorer on this PC; local sessions only)
    """

    async def process(self, input: dict, request: Request) -> dict | Response:
        action = str(input.get("action") or "")
        remote, who = caller(request)
        policy = fa.policy_for(remote)
        try:
            result = await asyncio.to_thread(self._run, action, input, policy, remote)
        except (fa.AccessDenied, fm.FileOpError, FileNotFoundError, FileExistsError, PermissionError, OSError) as exc:
            if action in AUDITED:
                access_control.audit(f"file_{action}_refused", by=who, path=_paths(input), error=str(exc)[:300])
            return {"ok": False, "error": _message(exc)}
        if action in AUDITED:
            access_control.audit(f"file_{action}", by=who, path=_paths(input), dest=input.get("dest") or None)
        return {"ok": True, **result}

    def _run(self, action: str, input: dict, policy: fa.Policy, remote: bool) -> dict:
        path, paths = str(input.get("path") or ""), [str(p) for p in input.get("paths") or []]
        name = str(input.get("name") or "")
        if action == "places":
            return fm.places(policy)
        if action == "locate":
            return fm.locate(path, policy)
        if action == "list":
            return fm.list_dir(path, policy, bool(input.get("show_hidden")))
        if action == "mkdir":
            return {"created": fm.mkdir(path, name, policy)}
        if action == "new_file":
            return {"created": fm.new_file(path, name, policy)}
        if action == "rename":
            return {"renamed": fm.rename(path, name, policy)}
        if action == "delete":
            return fm.delete(paths, policy, bool(input.get("permanent")))
        if action in ("copy", "move"):
            return {"created": fm.transfer(paths, str(input.get("dest") or ""), policy, move=action == "move")}
        if action == "read_text":
            return fm.read_text(path, policy)
        if action == "write_text":
            return fm.write_text(
                path, str(input.get("content") or ""), policy,
                str(input.get("encoding") or "utf-8"), input.get("expected_modified"),
                "\r\n" if input.get("newline") == "\r\n" else "\n",
            )
        if action == "reveal":
            if remote:
                raise fm.FileOpError("Opening File Explorer only works at this PC.")
            target = fa.resolve(path, policy)
            if target.is_dir():
                os.startfile(str(target))
            else:
                subprocess.Popen(["explorer", "/select,", str(target)])
            return {}
        raise fm.FileOpError(f"Unknown action: {action}")


def _paths(input: dict):
    return input.get("paths") or input.get("path") or ""


def _message(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        return "That file or folder no longer exists."
    if isinstance(exc, PermissionError):
        return "Windows denied access (the file may be in use or need administrator rights)."
    return str(exc) or exc.__class__.__name__

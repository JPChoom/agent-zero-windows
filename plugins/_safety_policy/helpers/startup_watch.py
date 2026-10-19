"""Startup tripwire: catch new Windows autostart entries an agent tool made.

Text matching (policy.py) can always be dodged by an agent determined to
get its way; this checks the result instead. Around every tool call that
can change the system it records the places Windows starts programs from at
sign-in, compares afterwards, and undoes anything new:

- `Run` / `RunOnce` values (HKCU, HKLM, HKLM WOW6432Node): new values are
  deleted, changed ones get their previous data back.
- The user's and the all-users Startup folders: new or changed files are
  moved into `usr/safety_quarantine/` (not deleted, so nothing is lost).
- Scheduled tasks outside Windows' own `\\Microsoft` folder (creating tasks
  there needs admin rights): the task definition is saved to the
  quarantine folder, then the task is deleted.
- Services: reported only. Creating one needs admin rights, and removing
  one is not something to do automatically.

Agent Zero's own autostart entry (plugins/_autostart) is never touched.
Every undo is written to the quarantine folder as JSON with what was
removed, so a wrongly removed entry can be restored by hand.

Limits: only these locations are watched (not Winlogon, IFEO, WMI
subscriptions, browser extensions, ...); a change made by another program
during the tool call is attributed to the tool; the HKLM keys, the
all-users folder and services can be undone only with admin rights.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from typing import Any

RUN_KEYS = (
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Run"),
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\RunOnce"),
    ("HKLM", r"Software\Microsoft\Windows\CurrentVersion\Run"),
    ("HKLM", r"Software\Microsoft\Windows\CurrentVersion\RunOnce"),
    ("HKLM", r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"),
)
SERVICES_KEY = r"SYSTEM\CurrentControlSet\Services"
OWN_RUN_VALUES = {"AgentZeroForWindows"}  # plugins/_autostart/helpers/startup.py VALUE_NAME


def startup_folders() -> list[str]:
    folders = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        folders.append(os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup"))
    programdata = os.environ.get("PROGRAMDATA")
    if programdata:
        folders.append(os.path.join(programdata, "Microsoft", "Windows", "Start Menu", "Programs", "StartUp"))
    return folders


@dataclass
class Snapshot:
    run_values: dict[str, Any] = field(default_factory=dict)   # "HKCU\\key\\name" -> data
    startup_files: dict[str, tuple[int, float]] = field(default_factory=dict)  # path -> (size, mtime)
    tasks: set[str] = field(default_factory=set)
    services: set[str] = field(default_factory=set)


@dataclass
class Change:
    kind: str          # run_value | startup_file | scheduled_task | service
    target: str        # what was added or changed
    detail: str = ""   # new data, file size, ...
    action: str = ""   # what the tripwire did
    ok: bool = True


# ---------------------------------------------------------------- reading

def _hive(name: str):
    import winreg

    return winreg.HKEY_CURRENT_USER if name == "HKCU" else winreg.HKEY_LOCAL_MACHINE


def _read_run_values() -> dict[str, Any]:
    import winreg

    values: dict[str, Any] = {}
    for hive, key in RUN_KEYS:
        try:
            with winreg.OpenKey(_hive(hive), key) as handle:
                index = 0
                while True:
                    try:
                        name, data, kind = winreg.EnumValue(handle, index)
                    except OSError:
                        break
                    values[f"{hive}\\{key}\\{name}"] = (data, kind)
                    index += 1
        except OSError:
            continue
    return values


def _read_startup_files() -> dict[str, tuple[int, float]]:
    files: dict[str, tuple[int, float]] = {}
    for folder in startup_folders():
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if entry.is_file(follow_symlinks=False) and entry.name.lower() != "desktop.ini":
                        stat = entry.stat(follow_symlinks=False)
                        files[entry.path] = (stat.st_size, stat.st_mtime)
        except OSError:
            continue
    return files


def _task_service():
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    service = win32com.client.Dispatch("Schedule.Service")
    service.Connect()
    return service


def _read_tasks() -> set[str]:
    names: set[str] = set()
    try:
        service = _task_service()
    except Exception:
        return names

    def walk(folder, top: bool) -> None:
        for task in folder.GetTasks(1):  # 1 = include hidden tasks
            names.add(task.Path)
        for sub in folder.GetFolders(0):
            if top and str(sub.Name).lower() == "microsoft":
                continue  # Windows' own tasks; writing there needs admin rights
            walk(sub, False)

    try:
        walk(service.GetFolder("\\"), True)
    except Exception:
        pass
    return names


def _read_services() -> set[str]:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, SERVICES_KEY) as handle:
            count = winreg.QueryInfoKey(handle)[0]
            return {winreg.EnumKey(handle, index) for index in range(count)}
    except OSError:
        return set()


def take_snapshot() -> Snapshot:
    return Snapshot(
        run_values=_read_run_values(),
        startup_files=_read_startup_files(),
        tasks=_read_tasks(),
        services=_read_services(),
    )


# ---------------------------------------------------------------- comparing

def compare(before: Snapshot, after: Snapshot) -> list[Change]:
    changes: list[Change] = []
    for target, value in after.run_values.items():
        name = target.rsplit("\\", 1)[-1]
        if name in OWN_RUN_VALUES:
            continue
        if before.run_values.get(target) != value:
            changes.append(Change("run_value", target, str(value[0])[:300]))
    for path, info in after.startup_files.items():
        if before.startup_files.get(path) != info:
            changes.append(Change("startup_file", path, f"{info[0]} bytes"))
    for task in sorted(after.tasks - before.tasks):
        changes.append(Change("scheduled_task", task))
    for service in sorted(after.services - before.services):
        changes.append(Change("service", service))
    return changes


# ---------------------------------------------------------------- undoing

def quarantine_dir() -> str:
    from helpers import files

    return files.get_abs_path("usr", "safety_quarantine", time.strftime("%Y%m%d-%H%M%S"))


def undo(changes: list[Change], before: Snapshot) -> str:
    """Undo what can be undone; returns the quarantine folder used ("" if none)."""
    folder = ""

    def ensure_folder() -> str:
        nonlocal folder
        if not folder:
            folder = quarantine_dir()
            os.makedirs(folder, exist_ok=True)
        return folder

    for change in changes:
        try:
            if change.kind == "run_value":
                _undo_run_value(change, before)
            elif change.kind == "startup_file":
                destination = os.path.join(ensure_folder(), os.path.basename(change.target))
                shutil.move(change.target, destination)
                change.action = f"moved to {destination}"
            elif change.kind == "scheduled_task":
                _undo_task(change, ensure_folder())
            else:
                change.action = "reported (not removed automatically)"
        except Exception as exc:
            change.ok = False
            change.action = f"could not undo: {exc}"

    if changes:
        try:
            record = {"when": time.strftime("%Y-%m-%dT%H:%M:%S"), "changes": [change.__dict__ for change in changes]}
            with open(os.path.join(ensure_folder(), "tripwire.json"), "w", encoding="utf-8") as handle:
                json.dump(record, handle, indent=2, default=str)
        except Exception:
            pass
    return folder


def _undo_run_value(change: Change, before: Snapshot) -> None:
    import winreg

    hive, rest = change.target.split("\\", 1)
    key, name = rest.rsplit("\\", 1)
    previous = before.run_values.get(change.target)
    with winreg.OpenKey(_hive(hive), key, 0, winreg.KEY_SET_VALUE) as handle:
        if previous is None:
            winreg.DeleteValue(handle, name)
            change.action = "deleted"
        else:
            winreg.SetValueEx(handle, name, 0, previous[1], previous[0])
            change.action = "restored the previous value"


def _undo_task(change: Change, folder: str) -> None:
    service = _task_service()
    parent, name = change.target.rsplit("\\", 1)
    task_folder = service.GetFolder(parent or "\\")
    task = task_folder.GetTask(name)
    safe_name = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in change.target.strip("\\")) or "task"
    with open(os.path.join(folder, safe_name + ".xml"), "w", encoding="utf-16") as handle:
        handle.write(task.Xml)
    task_folder.DeleteTask(name, 0)
    change.action = f"deleted (definition saved to {folder})"


def describe(changes: list[Change]) -> str:
    return "\n".join(f"- {change.kind}: {change.target} -> {change.action or 'found'}" for change in changes)

"""Access rules for the File Browser on a native Windows install.

Every file operation the browser performs goes through `resolve()` /
`resolve_new()`: the requested absolute path is resolved to its real
location (following symlinks and junctions) and must lie inside one of the
roots the current access policy allows, and must not be one of A0's own
secret files. Network (UNC) and device paths, relative paths and
alternate data streams are refused outright.

Policy (settings, written only through api/security_settings.py):
  file_browser_scope            "usr" | "a0_root" | "full"   (default a0_root)
  file_browser_remote_scope     "usr" | "a0_root" | "same"   (default a0_root)
  file_browser_allow_other_drives      other internal drives (default off)
  file_browser_allow_removable_drives  flash/SD/USB drives   (default off)

"full" is the whole Windows system drive (plus the drive A0 is on). Other
drives always need their toggle. A remote session (Remote Control tunnel)
gets the narrower of its cap and the local scope; the drive toggles apply
remotely only when the cap is "same". The configured workdir is always
reachable.
"""

from __future__ import annotations

import ctypes
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from helpers import files

SCOPES = ("usr", "a0_root", "full")
REMOTE_SCOPES = ("usr", "a0_root", "same")
DEFAULT_SCOPE = "a0_root"
DEFAULT_REMOTE_SCOPE = "a0_root"
SETTINGS_KEYS = (
    "file_browser_scope",
    "file_browser_remote_scope",
    "file_browser_allow_other_drives",
    "file_browser_allow_removable_drives",
)
_SCOPE_RANK = {name: rank for rank, name in enumerate(SCOPES)}

_DRIVE_PATH = re.compile(r"^[A-Za-z]:\\")
_INVALID_NAME_CHARS = set('<>:"/\\|?*') | {chr(c) for c in range(32)}
_RESERVED_NAMES = {"con", "prn", "aux", "nul"} | {f"{p}{n}" for p in ("com", "lpt") for n in range(1, 10)}
_DRIVE_CACHE_SECONDS = 5.0
_drive_cache: tuple[float, list[dict]] | None = None


class AccessDenied(Exception):
    """The path is outside what the current policy allows, or protected."""


# ------------------------------------------------------------------ path helpers

def _norm(path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def is_within(path, root) -> bool:
    """True when `path` is `root` or inside it (case-insensitive on Windows,
    whole path components only: C:\\a\\work does not contain C:\\a\\work2)."""
    p, r = _norm(path), _norm(root)
    try:
        return os.path.commonpath([p, r]) == r
    except ValueError:  # different drives
        return False


def a0_base() -> Path:
    return Path(os.path.realpath(files.get_base_dir()))


def workdir() -> Path:
    from helpers import settings

    return Path(os.path.realpath(settings.get_settings()["workdir_path"]))


def system_drive_root() -> str:
    return (os.environ.get("SystemDrive") or "C:").rstrip("\\") + "\\"


# ------------------------------------------------------------------ protected files

def is_protected(path) -> bool:
    """A0's own secrets: never listed, read, downloaded, edited, renamed or
    deleted through the browser, in any mode."""
    real = Path(os.path.realpath(str(path)))
    parts = [p.lower() for p in real.parts]
    name = parts[-1] if parts else ""

    # Project metadata can live anywhere (projects may have external roots).
    if ".a0proj" in parts:
        meta = parts[parts.index(".a0proj") + 1:]
        if name == "secrets.env" or (name == "config.json" and "plugins" in meta[:-1]):
            return True

    base = a0_base()
    if not is_within(real, base):
        return False
    rel = [p.lower() for p in real.relative_to(base).parts]
    if not rel:
        return False
    if rel == [".env"]:
        return True
    if rel[0] != "usr":
        return False
    sub = rel[1:]
    if not sub:
        return False
    if sub == [".env"] or sub == ["permissions_bypass.json"]:
        return True
    if len(sub) == 1 and sub[0].startswith("security_audit") and sub[0].endswith(".jsonl"):
        return True
    if name == "secrets.env":
        return True
    if sub[:2] == ["plugins", "_oauth"] or sub[:2] == ["whatsapp", "bridge-runtime"]:
        return True
    if name == "config.json" and sub[0] in ("plugins", "agents") and "plugins" in sub[:-1]:
        return True
    return False


def contains_protected(folder, limit: int = 20000) -> bool:
    """Whether deleting, renaming or zipping `folder` would touch a protected
    file. Walks at most `limit` entries; past that it answers True (refuse)."""
    if is_protected(folder):
        return True
    seen = 0
    for root, dirs, names in os.walk(folder):
        for name in dirs + names:
            seen += 1
            if seen > limit or is_protected(os.path.join(root, name)):
                return True
    return False


# ------------------------------------------------------------------ drives

def _bus_type(root: str) -> int | None:
    """Storage bus type of the disk behind a drive letter (7 = USB, 12 = SD,
    13 = MMC), read with IOCTL_STORAGE_QUERY_PROPERTY. No admin needed."""
    if os.name != "nt":
        return None
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    handle = kernel32.CreateFileW(
        f"\\\\.\\{root[:2]}", 0, 0x1 | 0x2, None, 3, 0, None  # share read|write, OPEN_EXISTING
    )
    if not handle or handle == wintypes.HANDLE(-1).value:
        return None
    try:
        query = (ctypes.c_uint32 * 3)(0, 0, 0)  # StorageDeviceProperty, PropertyStandardQuery
        out = ctypes.create_string_buffer(1024)
        returned = wintypes.DWORD()
        ok = kernel32.DeviceIoControl(
            wintypes.HANDLE(handle), 0x002D1400, query, ctypes.sizeof(query),
            out, ctypes.sizeof(out), ctypes.byref(returned), None,
        )
        if not ok or returned.value < 32:
            return None
        return int.from_bytes(out.raw[28:32], "little")
    finally:
        kernel32.CloseHandle(wintypes.HANDLE(handle))


def _volume_label(root: str) -> str:
    buf = ctypes.create_unicode_buffer(261)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(root, buf, 261, None, None, None, None, 0)
    return buf.value if ok else ""


def list_drives(force: bool = False) -> list[dict]:
    """Every drive with media: letter root, label, kind (system / fixed /
    removable / network / cdrom), sizes. USB and SD disks count as removable
    even when Windows reports them as fixed."""
    global _drive_cache
    now = time.monotonic()
    if not force and _drive_cache and now - _drive_cache[0] < _DRIVE_CACHE_SECONDS:
        return [dict(d) for d in _drive_cache[1]]
    if os.name != "nt":
        drives = [{"root": "/", "label": "", "kind": "system", "total": 0, "free": 0}]
        _drive_cache = (now, drives)
        return drives

    kernel32 = ctypes.windll.kernel32
    mask = kernel32.GetLogicalDrives()
    system_root = _norm(system_drive_root())
    a0_root = _norm(a0_base().anchor)
    drives = []
    for i in range(26):
        if not mask & (1 << i):
            continue
        root = f"{chr(65 + i)}:\\"
        drive_type = kernel32.GetDriveTypeW(root)
        if drive_type in (0, 1):
            continue
        try:
            usage = shutil.disk_usage(root)
        except OSError:
            continue  # card reader or optical drive without media
        if drive_type == 4:
            kind = "network"
        elif drive_type == 5:
            kind = "cdrom"
        elif _norm(root) in (system_root, a0_root):
            kind = "system"
        elif drive_type == 2 or _bus_type(root) in (7, 12, 13):
            kind = "removable"
        else:
            kind = "fixed"
        drives.append({
            "root": root, "label": _volume_label(root), "kind": kind,
            "total": usage.total, "free": usage.free,
        })
    _drive_cache = (now, drives)
    return [dict(d) for d in drives]


# ------------------------------------------------------------------ policy

@dataclass
class Policy:
    scope: str
    remote: bool
    allow_other_drives: bool
    allow_removable_drives: bool
    roots: list[str] = field(default_factory=list)

    def allows(self, path) -> bool:
        return any(is_within(path, root) for root in self.roots)

    def describe(self) -> dict:
        return {
            "scope": self.scope, "remote": self.remote, "roots": list(self.roots),
            "allow_other_drives": self.allow_other_drives,
            "allow_removable_drives": self.allow_removable_drives,
        }


def read_settings() -> dict:
    from helpers import settings

    s = settings.get_settings()
    scope = s.get("file_browser_scope")
    remote_scope = s.get("file_browser_remote_scope")
    return {
        "file_browser_scope": scope if scope in SCOPES else DEFAULT_SCOPE,
        "file_browser_remote_scope": remote_scope if remote_scope in REMOTE_SCOPES else DEFAULT_REMOTE_SCOPE,
        "file_browser_allow_other_drives": bool(s.get("file_browser_allow_other_drives", False)),
        "file_browser_allow_removable_drives": bool(s.get("file_browser_allow_removable_drives", False)),
    }


def policy_for(remote: bool, config: dict | None = None) -> Policy:
    cfg = config or read_settings()
    scope = cfg["file_browser_scope"]
    other, removable = cfg["file_browser_allow_other_drives"], cfg["file_browser_allow_removable_drives"]
    if remote and cfg["file_browser_remote_scope"] != "same":
        cap = cfg["file_browser_remote_scope"]
        scope = min(scope, cap, key=_SCOPE_RANK.__getitem__)
        other = removable = False

    base = a0_base()
    roots = [str(base / "usr")] if scope == "usr" else [str(base)]
    if scope == "full":
        # The Windows drive, plus A0's own drive if different (listed as "system").
        roots = [system_drive_root(), str(base)] + [d["root"] for d in list_drives() if d["kind"] == "system"]
    roots.append(str(workdir()))
    if other or removable:
        for drive in list_drives():
            if (other and drive["kind"] == "fixed") or (removable and drive["kind"] == "removable"):
                roots.append(drive["root"])

    unique: list[str] = []
    for root in roots:
        if not any(_norm(root) == _norm(u) for u in unique):
            unique.append(root)
    return Policy(scope, remote, other, removable, unique)


def widens(new: dict, old: dict) -> bool:
    """Whether `new` settings give local or remote sessions more access than `old`."""
    for remote in (False, True):
        before, after = policy_for(remote, old), policy_for(remote, new)
        if any(not before.allows(root) for root in after.roots):
            return True
    return False


# ------------------------------------------------------------------ resolution

def _check_shape(raw) -> str:
    text = str(raw or "").strip().replace("/", "\\")
    if not text:
        raise AccessDenied("No path given.")
    if "\0" in text:
        raise AccessDenied("Invalid path.")
    if text.startswith("\\\\"):
        raise AccessDenied("Network and device paths can't be opened here.")
    if re.fullmatch(r"[A-Za-z]:\\?", text):
        text = text[:2] + "\\"
    if not _DRIVE_PATH.match(text):
        raise AccessDenied("Use a full path that starts with a drive, such as C:\\Users.")
    if ":" in text[2:]:
        raise AccessDenied("Invalid path.")
    for part in text[3:].split("\\"):
        if part.split(".")[0].strip().lower() in _RESERVED_NAMES:
            raise AccessDenied("Invalid path.")  # device names (NUL, CON, COM1...) can hang a read
    return text


def resolve(raw, policy: Policy, *, must_exist: bool = True) -> Path:
    """The real, allowed location of an existing path (or a not-yet-existing
    one with must_exist=False). Raises AccessDenied / FileNotFoundError."""
    real = os.path.realpath(_check_shape(raw))
    if not _DRIVE_PATH.match(real):  # a link that points at a network or device path
        raise AccessDenied("Invalid path.")
    if not policy.allows(real):
        raise AccessDenied("That location is outside what the File Browser may open (Settings > Security).")
    if is_protected(real):
        raise AccessDenied("That is one of Agent Zero's protected files.")
    path = Path(real)
    if must_exist and not path.exists():
        raise FileNotFoundError(f"Not found: {raw}")
    return path


def validate_name(name: str) -> str:
    name = str(name or "")
    stem = name.split(".")[0].strip().lower()
    if (
        not name.strip() or name in (".", "..") or len(name) > 255
        or any(ch in _INVALID_NAME_CHARS for ch in name)
        or name[-1] in ". " or stem in _RESERVED_NAMES
    ):
        raise AccessDenied(f"{name!r} is not a valid Windows file name.")
    return name


def resolve_new(folder, name: str, policy: Policy) -> Path:
    """Location for a new item `name` inside existing allowed `folder`."""
    parent = resolve(folder, policy)
    if not parent.is_dir():
        raise AccessDenied("The target is not a folder.")
    target = parent / validate_name(name)
    if not policy.allows(target) or is_protected(target):
        raise AccessDenied("That name can't be used here.")
    return target

"""File Browser operations on real Windows paths. Every path is checked by
helpers/file_access.py against the caller's policy before anything is read
or changed; callers pass that policy in."""

from __future__ import annotations

import ctypes
import os
import re
import shutil
import stat
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from helpers import file_access as fa

MAX_ENTRIES = 10000
MAX_TEXT_BYTES = 2 * 1024 * 1024
_KNOWN_FOLDERS = {
    "Desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "Documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "Downloads": "374DE290-123F-4565-9164-39C4925E467B",
    "Pictures": "33E28130-4E1E-4676-835A-98395C3BC3BB",
    "Music": "4BD8D571-6D19-48D3-BE97-422220080E43",
    "Videos": "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
}


class FileOpError(Exception):
    pass


# ------------------------------------------------------------------ listing

def _entry(path: Path, policy: fa.Policy, st=None) -> dict:
    st = st or path.stat()
    attrs = getattr(st, "st_file_attributes", 0)
    is_dir = stat.S_ISDIR(st.st_mode)
    entry = {
        "name": path.name or str(path),
        "path": str(path),
        "is_dir": is_dir,
        "size": 0 if is_dir else st.st_size,
        "modified": int(st.st_mtime * 1000),
        "ext": "" if is_dir else path.suffix.lower().lstrip("."),
        "hidden": bool(attrs & stat.FILE_ATTRIBUTE_HIDDEN) or path.name.startswith("."),
        "system": bool(attrs & stat.FILE_ATTRIBUTE_SYSTEM),
        "readonly": bool(attrs & stat.FILE_ATTRIBUTE_READONLY),
    }
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        entry["is_link"] = True
        entry["outside"] = not policy.allows(os.path.realpath(path))
    return entry


def list_dir(raw: str, policy: fa.Policy, show_hidden: bool = False) -> dict:
    folder = fa.resolve(raw, policy)
    if not folder.is_dir():
        raise FileOpError("That is a file, not a folder.")
    entries, truncated, hidden_count = [], False, 0
    try:
        iterator = os.scandir(folder)
    except PermissionError:
        raise FileOpError("Windows denied access to this folder.")
    with iterator:
        for item in iterator:
            path = Path(item.path)
            if fa.is_protected(path):
                continue
            try:
                entry = _entry(path, policy, item.stat(follow_symlinks=True))
            except OSError:
                continue  # broken link, locked system file
            if (entry["hidden"] or entry["system"]) and not show_hidden:
                hidden_count += 1
                continue
            entries.append(entry)
            if len(entries) >= MAX_ENTRIES:
                truncated = True
                break
    parent = folder.parent if folder.parent != folder else None
    return {
        "path": str(folder),
        "parent": str(parent) if parent and policy.allows(parent) else "",
        "entries": entries,
        "truncated": truncated,
        "hidden_count": hidden_count,
        "writable": os.access(folder, os.W_OK),
        "drive_kind": _drive_kind(folder),
    }


def _drive_kind(path: Path) -> str:
    anchor = fa._norm(Path(path).anchor)
    for drive in fa.list_drives():
        if fa._norm(drive["root"]) == anchor:
            return drive["kind"]
    return "fixed"


def _known_folder(guid: str) -> str:
    if os.name != "nt":
        return ""
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    u = uuid.UUID(guid)
    g = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))
    out = ctypes.c_wchar_p()
    shell32 = ctypes.windll.shell32
    if shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) != 0:
        return ""
    try:
        return out.value or ""
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)


def places(policy: fa.Policy) -> dict:
    """Quick access folders and drives this policy can open."""
    quick = [{"name": "Workdir", "path": str(fa.workdir()), "icon": "work"}]
    base = fa.a0_base()
    if policy.allows(base):
        quick.append({"name": "Agent Zero", "path": str(base), "icon": "smart_toy"})
    elif policy.allows(base / "usr"):
        quick.append({"name": "Agent Zero data", "path": str(base / "usr"), "icon": "smart_toy"})
    for name, guid in _KNOWN_FOLDERS.items():
        path = _known_folder(guid)
        if path and os.path.isdir(path) and policy.allows(path):
            quick.append({"name": name, "path": path, "icon": name.lower()})
    drives = []
    for drive in fa.list_drives():
        if drive["kind"] in ("network", "cdrom"):
            continue
        allowed = policy.allows(drive["root"])
        # A drive whose root is off-limits is still shown (locked) if part of it is
        # reachable, e.g. C:\ when only the A0 folder may be opened.
        partly = any(fa.is_within(root, drive["root"]) for root in policy.roots)
        if allowed or partly or not policy.remote:
            drives.append({**drive, "allowed": allowed, "partly": partly and not allowed})
    return {"quick": quick, "drives": drives, "policy": policy.describe()}


def translate(raw: str) -> str:
    """The Windows path for the path forms other features pass in: "",
    "$WORK_DIR", Docker-style "/a0/...", "file://" URLs, workdir-relative "x"
    or "/x", or a Windows path. Not yet checked against any policy."""
    text = str(raw or "").strip()
    if text.lower().startswith("file://"):
        from urllib.parse import unquote

        text = unquote(text[7:])
        if re.match(r"^/[A-Za-z]:", text):
            text = text[1:]
    if text in ("", "$WORK_DIR", "/a0/usr/workdir"):
        return str(fa.workdir())
    if text == "/a0" or text.startswith("/a0/"):
        return str(fa.a0_base() / text[4:].lstrip("/"))
    if re.match(r"^[A-Za-z]:([\\/]|$)", text):
        return text
    return str(fa.workdir() / text.lstrip("/\\"))


def locate(raw: str, policy: fa.Policy) -> dict:
    """{folder, select} for any path form `translate` accepts: the folder to
    show and, when `raw` named a file, that file to highlight."""
    path = fa.resolve(translate(raw), policy)
    if path.is_dir():
        return {"folder": str(path), "select": ""}
    return {"folder": str(path.parent), "select": str(path)}


# ------------------------------------------------------------------ changes

def _unique(target: Path) -> Path:
    if not target.exists():
        return target
    stem, suffix = (target.stem, target.suffix) if target.is_file() or "." in target.name else (target.name, "")
    n = 2
    while True:
        candidate = target.with_name(f"{stem} ({n}){suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def mkdir(folder: str, name: str, policy: fa.Policy) -> str:
    target = fa.resolve_new(folder, name, policy)
    if target.exists():
        raise FileOpError(f"{name} already exists.")
    target.mkdir()
    return str(target)


def new_file(folder: str, name: str, policy: fa.Policy) -> str:
    target = fa.resolve_new(folder, name, policy)
    if target.exists():
        raise FileOpError(f"{name} already exists.")
    target.touch()
    return str(target)


def _check_whole(path: Path) -> None:
    if path.is_dir() and fa.contains_protected(path):
        raise FileOpError(f"{path.name} contains Agent Zero's protected files, so it can't be changed here.")


def rename(raw: str, new_name: str, policy: fa.Policy) -> str:
    source = fa.resolve(raw, policy)
    if source.parent == source:
        raise FileOpError("A drive can't be renamed here.")
    _check_whole(source)
    target = fa.resolve_new(source.parent, new_name, policy)
    if target.exists() and fa._norm(target) != fa._norm(source):
        raise FileOpError(f"{new_name} already exists.")
    source.rename(target)
    return str(target)


def _recycle(paths: list[Path]) -> None:
    """Send to the Recycle Bin (SHFileOperationW, FOF_ALLOWUNDO), no dialogs."""
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    op = SHFILEOPSTRUCTW()
    op.wFunc = 3  # FO_DELETE
    op.pFrom = "\0".join(str(p) for p in paths) + "\0\0"
    op.fFlags = 0x40 | 0x10 | 0x4 | 0x400  # ALLOWUNDO | NOCONFIRMATION | SILENT | NOERRORUI
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if result != 0 or op.fAnyOperationsAborted:
        raise FileOpError(f"Windows could not move the items to the Recycle Bin (code {result}).")


def delete(raws: list[str], policy: fa.Policy, permanent: bool = False) -> dict:
    paths = [fa.resolve(raw, policy) for raw in raws]
    for path in paths:
        if path.parent == path:
            raise FileOpError("A drive can't be deleted.")
        if any(fa.is_within(root, path) for root in policy.roots):
            raise FileOpError(f"{path} is one of the File Browser's top folders and can't be deleted here.")
        _check_whole(path)
    # Removable and network drives have no Recycle Bin: Windows would delete outright.
    recyclable = not permanent and os.name == "nt" and all(_drive_kind(p) not in ("removable", "network") for p in paths)
    if recyclable:
        _recycle(paths)
    else:
        for path in paths:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
    return {"deleted": [str(p) for p in paths], "recycled": recyclable}


def transfer(raws: list[str], dest_folder: str, policy: fa.Policy, move: bool) -> list[str]:
    dest = fa.resolve(dest_folder, policy)
    if not dest.is_dir():
        raise FileOpError("The destination is not a folder.")
    done = []
    for raw in raws:
        source = fa.resolve(raw, policy)
        _check_whole(source)
        if source.is_dir() and fa.is_within(dest, source):
            raise FileOpError(f"{source.name} can't be put inside itself.")
        if move and fa._norm(source.parent) == fa._norm(dest):
            continue
        target = _unique(fa.resolve_new(dest, source.name, policy))
        if move:
            shutil.move(str(source), str(target))
        elif source.is_dir():
            shutil.copytree(source, target, symlinks=True)
        else:
            shutil.copy2(source, target)
        done.append(str(target))
    return done


def save_upload(dest_folder: str, filename: str, stream, policy: fa.Policy, overwrite: bool = False) -> str:
    name = os.path.basename(str(filename or "").replace("\\", "/"))
    target = fa.resolve_new(dest_folder, name, policy)
    if target.exists():
        if target.is_dir():
            raise FileOpError(f"A folder named {name} already exists.")
        if not overwrite:
            target = _unique(target)
    partial = target.with_name(target.name + ".part-" + uuid.uuid4().hex[:8])
    try:
        with open(partial, "wb") as fh:
            shutil.copyfileobj(stream, fh, 1024 * 1024)
        os.replace(partial, target)
    finally:
        if partial.exists():
            partial.unlink()
    return str(target)


# ------------------------------------------------------------------ text

def read_text(raw: str, policy: fa.Policy) -> dict:
    path = fa.resolve(raw, policy)
    if not path.is_file():
        raise FileOpError("Not a file.")
    if path.stat().st_size > MAX_TEXT_BYTES:
        raise FileOpError("The file is larger than 2 MB, too big to edit here.")
    data = path.read_bytes()
    if b"\0" in data[:8192]:
        raise FileOpError("This looks like a binary file, so it can't be edited as text.")
    text, encoding = data.decode("latin-1"), "latin-1"  # never fails; replaced below when possible
    for candidate in ("utf-8-sig", "cp1252"):
        try:
            text, encoding = data.decode(candidate), candidate
            break
        except UnicodeDecodeError:
            continue
    if encoding == "utf-8-sig" and not data.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8"
    # Browsers turn every line ending in a text box into "\n"; report the
    # file's style so write_text can restore it.
    newline = "\r\n" if text.count("\r\n") * 2 > text.count("\n") else "\n"
    return {
        "path": str(path), "content": text.replace("\r\n", "\n"), "encoding": encoding, "newline": newline,
        "modified": int(path.stat().st_mtime * 1000),
    }


def write_text(
    raw: str, content: str, policy: fa.Policy, encoding: str = "utf-8",
    expected_modified: int | None = None, newline: str = "\n",
) -> dict:
    path = fa.resolve(raw, policy, must_exist=False)
    if not path.exists():
        path = fa.resolve_new(path.parent, path.name, policy)
    elif path.is_dir():
        raise FileOpError("That is a folder.")
    if path.exists() and expected_modified and int(path.stat().st_mtime * 1000) != int(expected_modified):
        raise FileOpError("The file changed on disk since it was opened. Reload it before saving.")
    text = str(content).replace("\r\n", "\n")
    if newline == "\r\n":
        text = text.replace("\n", "\r\n")
    data = text.encode(encoding if encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1") else "utf-8")
    if len(data) > MAX_TEXT_BYTES:
        raise FileOpError("The text is larger than 2 MB.")
    with open(path, "wb") as fh:
        fh.write(data)
    return {"path": str(path), "modified": int(path.stat().st_mtime * 1000)}


# ------------------------------------------------------------------ download

def zip_selection(raws: list[str], policy: fa.Policy) -> tuple[str, str]:
    """ZIP the selection into a temp file. Every file is re-checked by its
    real location, so a link inside a folder can't pull outside files in;
    protected files are left out. Returns (zip path, download name)."""
    sources = [fa.resolve(raw, policy) for raw in raws]
    handle, zip_path = tempfile.mkstemp(prefix="a0-download-", suffix=".zip")
    os.close(handle)
    used: set[str] = set()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for source in sources:
            arc_root = source.name or source.anchor.strip(":\\") or "drive"
            while arc_root in used:
                arc_root += "_"
            used.add(arc_root)
            if source.is_file():
                zf.write(source, arc_root)
                continue
            for root, dirs, names in os.walk(source):
                dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d)) and not _is_junction(os.path.join(root, d))]
                for name in names:
                    full = os.path.join(root, name)
                    real = os.path.realpath(full)
                    if not policy.allows(real) or fa.is_protected(real):
                        continue
                    rel = os.path.relpath(full, source)
                    try:
                        zf.write(full, f"{arc_root}/{Path(rel).as_posix()}")
                    except (PermissionError, OSError):
                        continue  # locked file (e.g. in use)
    name = f"{sources[0].name or 'drive'}.zip" if len(sources) == 1 else f"selection-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.zip"
    return zip_path, name


def _is_junction(path: str) -> bool:
    try:
        return Path(path).is_junction()
    except (AttributeError, OSError):
        return False

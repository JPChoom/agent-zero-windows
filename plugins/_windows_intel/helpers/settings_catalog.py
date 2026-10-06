"""The windows_setting catalog: a few safe, reversible per-user settings.

A standard Windows account can't (and Agent Zero shouldn't) change services,
firewall or accounts. What it can usefully automate is per-user preferences,
so the catalog is a fixed list: each setting has a known registry value or
API, a closed set of allowed values, and a way to apply it immediately.
Nothing here touches Run keys, services, firewall or accounts, and nothing
outside this list can be written.

All system access goes through `Backend`, so tests use a fake one.
"""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_ADVANCED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
_PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
_GUID_RE = re.compile(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\s+\((.+?)\)(\s*\*)?")
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp"}


class SettingError(ValueError):
    pass


class Backend:
    """Real Windows access (HKCU only)."""

    def reg_get(self, path: str, name: str):
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
                return winreg.QueryValueEx(k, name)[0]
        except OSError:
            return None

    def reg_set_dword(self, path: str, name: str, value: int) -> None:
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, int(value))

    def broadcast(self, area: str) -> None:
        """WM_SETTINGCHANGE so running apps pick the change up."""
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, area, 0x0002, 3000, ctypes.byref(result))

    def explorer_refresh(self) -> None:
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)  # SHCNE_ASSOCCHANGED

    def powercfg(self, *args: str) -> tuple[int, str]:
        exe = os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32", "powercfg.exe")
        p = subprocess.run([exe, *args], capture_output=True, text=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return p.returncode, (p.stdout or "") + (p.stderr or "")

    def wallpaper_get(self) -> str:
        buf = ctypes.create_unicode_buffer(520)
        ctypes.windll.user32.SystemParametersInfoW(0x0073, 520, buf, 0)
        return buf.value

    def wallpaper_set(self, path: str) -> bool:
        return bool(ctypes.windll.user32.SystemParametersInfoW(0x0014, 0, path, 0x01 | 0x02))

    def windows_build(self) -> int:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as k:
                return int(winreg.QueryValueEx(k, "CurrentBuild")[0])
        except (OSError, ValueError):
            return 0


@dataclass(frozen=True)
class Setting:
    name: str
    summary: str
    get: Callable[[Backend], str]
    set: Callable[[Backend, str], None]
    choices: Callable[[Backend], list[str]]
    available: Callable[[Backend], str] = lambda b: ""  # reason it is unavailable, or ""


# -- registry DWORD settings ---------------------------------------------------------------

def _dword_setting(name, summary, path, value_names, mapping, refresh, available=lambda b: ""):
    reverse = {v: k for k, v in mapping.items()}

    def get(b: Backend) -> str:
        raw = b.reg_get(path, value_names[0])
        if raw is None:
            return "Windows default (not set)"
        return reverse.get(raw, f"unknown ({raw})")

    def set_(b: Backend, value: str) -> None:
        for vn in value_names:
            b.reg_set_dword(path, vn, mapping[value])
        refresh(b)

    return Setting(name, summary, get, set_, lambda b: list(mapping), available)


def _win11_only(b: Backend) -> str:
    return "" if b.windows_build() >= 22000 else "needs Windows 11"


# -- power plan -----------------------------------------------------------------------------

def _plans(b: Backend) -> list[tuple[str, str, bool]]:
    rc, out = b.powercfg("/list")
    if rc != 0:
        raise SettingError("powercfg could not list power plans")
    return [(m.group(1).lower(), m.group(2).strip(), bool(m.group(3))) for m in _GUID_RE.finditer(out)]


def _plan_get(b: Backend) -> str:
    for _, name, active in _plans(b):
        if active:
            return name
    return "unknown"


def _plan_set(b: Backend, value: str) -> None:
    for guid, name, _ in _plans(b):
        if name.lower() == value.lower():
            rc, out = b.powercfg("/setactive", guid)
            if rc != 0:
                raise SettingError(f"powercfg refused: {out.strip()[:200]}")
            return
    raise SettingError(f"no power plan named {value!r}")


# -- wallpaper -------------------------------------------------------------------------------

def wallpaper_roots() -> list[Path]:
    from helpers import files

    roots = [Path(files.get_abs_path("usr", "uploads")), Path(files.get_abs_path("usr", "workdir"))]
    try:
        from helpers import settings

        workdir = str(settings.get_settings().get("workdir_path") or "")
        if workdir:
            roots.append(Path(workdir))
    except Exception:
        pass
    return roots


def check_wallpaper_path(value: str, roots: list[Path]) -> Path:
    path = Path(value).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise SettingError(f"{value!r} does not exist")
    if resolved.suffix.lower() not in _IMAGE_EXTS:
        raise SettingError("the wallpaper must be a .png, .jpg, .jpeg or .bmp file")
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return resolved
        except (ValueError, OSError):
            continue
    raise SettingError("the wallpaper must be inside the agent's work folder or usr/uploads")


def _wallpaper_set(b: Backend, value: str) -> None:
    path = check_wallpaper_path(value, wallpaper_roots())
    if not b.wallpaper_set(str(path)):
        raise SettingError("Windows refused the wallpaper change")


# -- the catalog -------------------------------------------------------------------------------

CATALOG: dict[str, Setting] = {s.name: s for s in [
    _dword_setting("theme", "light or dark mode for apps and Windows", _PERSONALIZE,
                   ["AppsUseLightTheme", "SystemUsesLightTheme"], {"light": 1, "dark": 0},
                   lambda b: b.broadcast("ImmersiveColorSet")),
    _dword_setting("file_extensions", "show or hide file name extensions in Explorer", _ADVANCED,
                   ["HideFileExt"], {"show": 0, "hide": 1}, lambda b: b.explorer_refresh()),
    _dword_setting("hidden_files", "show or hide hidden files in Explorer", _ADVANCED,
                   ["Hidden"], {"show": 1, "hide": 2}, lambda b: b.explorer_refresh()),
    _dword_setting("taskbar_alignment", "taskbar icons on the left or centered", _ADVANCED,
                   ["TaskbarAl"], {"center": 1, "left": 0}, lambda b: b.broadcast("TraySettings"), _win11_only),
    Setting("power_plan", "active power plan (existing plans only)", _plan_get, _plan_set,
            lambda b: [name for _, name, _ in _plans(b)]),
    Setting("wallpaper", "desktop wallpaper (an image inside the work folder or usr/uploads)",
            lambda b: b.wallpaper_get() or "(none)", _wallpaper_set, lambda b: ["<image path>"]),
]}


def normalize_value(setting: Setting, value: str, backend: Backend) -> str:
    text = str(value or "").strip()
    if not text:
        raise SettingError(f"{setting.name} needs a value")
    if setting.name == "wallpaper":
        return text
    choices = setting.choices(backend)
    for choice in choices:
        if choice.lower() == text.lower():
            return choice
    raise SettingError(f"{setting.name} must be one of: {', '.join(choices)}")

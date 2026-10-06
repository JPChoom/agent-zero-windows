"""In-process sources for windows_info: psutil, winreg, win32 - no PowerShell,
no command line, no start-up cost. Each function takes validated arguments
(helpers/validate.py) plus the resolved config, and returns finished text.
"""

from __future__ import annotations

import ctypes
import os
import platform
import time
from datetime import datetime
from pathlib import Path

from plugins._windows_intel.helpers import fmt

# -- registry access policy ----------------------------------------------------------

# Broad allowlist (owner decision 2026-10-06). Prefixes, case-insensitive.
REGISTRY_ALLOW = (
    "HKLM\\SOFTWARE",
    "HKCU\\SOFTWARE",
    "HKLM\\SYSTEM\\CurrentControlSet\\Services",
    "HKLM\\SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment",
    "HKCU\\Environment",
    "HKCU\\Control Panel",
    "HKCU\\Keyboard Layout",
)
# Never read, wherever they appear in the path: credential stores, DPAPI,
# device identity, saved browser/IE form secrets, account tokens.
REGISTRY_DENY = (
    "\\SAM", "\\SECURITY", "CREDENTIALS", "\\PROTECT", "\\VAULT", "\\CRYPTOGRAPHY",
    "IDENTITYCRL", "TOKENBROKER", "INTELLIFORMS", "\\STORAGE2", "\\LSA", "\\SECRETS",
)


def registry_refusal(path: str) -> str:
    """Reason a normalized registry path may not be read, or ""."""
    upper = path.upper()
    if not any(upper == p.upper() or upper.startswith(p.upper() + "\\") for p in REGISTRY_ALLOW):
        return (
            "that key is outside what windows_info reads. Allowed roots: "
            + ", ".join(REGISTRY_ALLOW)
        )
    for bad in REGISTRY_DENY:
        if bad in upper + "\\":
            return "that key holds credentials or protected data; windows_info never reads it"
    return ""


def _winreg():
    import winreg

    return winreg


def _open(path: str):
    winreg = _winreg()
    root, _, sub = path.partition("\\")
    hive = winreg.HKEY_LOCAL_MACHINE if root == "HKLM" else winreg.HKEY_CURRENT_USER
    return winreg.OpenKey(hive, sub, 0, winreg.KEY_READ)


def _value_text(winreg, name: str, data, kind) -> str:
    if kind == winreg.REG_BINARY:
        raw = bytes(data or b"")
        return f"<{len(raw)} bytes> {raw[:16].hex(' ')}{' ...' if len(raw) > 16 else ''}"
    if kind == winreg.REG_MULTI_SZ:
        data = "; ".join(data or [])
    return fmt.mask_value(name, data)


def _kind_name(winreg, kind) -> str:
    names = {
        winreg.REG_SZ: "SZ", winreg.REG_EXPAND_SZ: "EXPAND_SZ", winreg.REG_DWORD: "DWORD",
        winreg.REG_QWORD: "QWORD", winreg.REG_BINARY: "BINARY", winreg.REG_MULTI_SZ: "MULTI_SZ",
    }
    return names.get(kind, str(kind))


def registry(args: dict, cfg: dict) -> str:
    winreg = _winreg()
    path = args["path"]
    refused = registry_refusal(path)
    if refused:
        return f"Refused: {refused}."
    try:
        key = _open(path)
    except FileNotFoundError:
        return f"{path} does not exist."
    except PermissionError:
        return f"{path}: access denied (Agent Zero runs as a standard user)."
    with key:
        if args.get("value"):
            try:
                data, kind = winreg.QueryValueEx(key, args["value"])
            except FileNotFoundError:
                return f"{path} has no value named {args['value']!r}."
            return fmt.record([
                ("key", path), ("value", args["value"]), ("type", _kind_name(winreg, kind)),
                ("data", _value_text(winreg, args["value"], data, kind)),
            ], max_chars=cfg["max_output_chars"], width=2000)
        rows, i = [], 0
        while True:
            try:
                name, data, kind = winreg.EnumValue(key, i)
            except OSError:
                break
            rows.append((name or "(default)", _kind_name(winreg, kind), _value_text(winreg, name, data, kind)))
            i += 1
        out = [f"{path}", fmt.table(["value", "type", "data"], rows, limit=cfg["max_limit"],
                                    max_chars=cfg["max_output_chars"] // 2, widths={"data": 160})]
        if args.get("depth", 0) >= 1:
            subs, j = [], 0
            while True:
                try:
                    subs.append((winreg.EnumKey(key, j),))
                except OSError:
                    break
                j += 1
            out.append("subkeys:\n" + fmt.table(["name"], subs, limit=cfg["max_limit"],
                                                max_chars=cfg["max_output_chars"] // 2))
        return "\n".join(out)


def _read_values(path: str) -> dict:
    """All values of a key as {name: data}; {} if missing. Internal reads only."""
    winreg = _winreg()
    try:
        key = _open(path)
    except OSError:
        return {}
    out, i = {}, 0
    with key:
        while True:
            try:
                name, data, _ = winreg.EnumValue(key, i)
            except OSError:
                break
            out[name] = data
            i += 1
    return out


def _subkeys(path: str) -> list[str]:
    winreg = _winreg()
    try:
        key = _open(path)
    except OSError:
        return []
    out, i = [], 0
    with key:
        while True:
            try:
                out.append(winreg.EnumKey(key, i))
            except OSError:
                break
            i += 1
    return out


# -- system ---------------------------------------------------------------------------------

def system(args: dict, cfg: dict) -> str:
    import psutil

    cv = _read_values("HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion")
    build = str(cv.get("CurrentBuild") or platform.version().split(".")[-1])
    product = str(cv.get("ProductName") or "Windows")
    if build.isdigit() and int(build) >= 22000:
        product = product.replace("Windows 10", "Windows 11")  # ProductName still says 10 on Windows 11
    ubr = cv.get("UBR")
    cpu = _read_values("HKLM\\HARDWARE\\DESCRIPTION\\System\\CentralProcessor\\0").get("ProcessorNameString", "")
    vm = psutil.virtual_memory()
    boot = psutil.boot_time()
    up = time.time() - boot
    return fmt.record([
        ("os", f"{product} {cv.get('DisplayVersion') or ''}".strip()),
        ("build", f"{build}.{ubr}" if ubr is not None else build),
        ("edition", cv.get("EditionID")),
        ("architecture", platform.machine()),
        ("uptime", f"{int(up // 86400)}d {int(up % 86400 // 3600)}h {int(up % 3600 // 60)}m"),
        ("booted", datetime.fromtimestamp(boot).strftime("%Y-%m-%d %H:%M")),
        ("cpu", str(cpu).strip()),
        ("cores", f"{psutil.cpu_count(logical=False)} physical, {psutil.cpu_count()} logical"),
        ("cpu load", f"{psutil.cpu_percent(interval=0.3):.0f}%"),
        ("memory", f"{fmt.human_bytes(vm.total - vm.available)} used of {fmt.human_bytes(vm.total)} ({vm.percent:.0f}%)"),
    ], max_chars=cfg["max_output_chars"])


# -- processes ------------------------------------------------------------------------------

def processes(args: dict, cfg: dict) -> str:
    import psutil

    me = psutil.Process().username()
    wanted_name = (args.get("name") or "").lower()
    procs = []
    for p in psutil.process_iter(["pid", "name", "username", "memory_info", "create_time"]):
        info = p.info
        if args.get("pid") is not None and info["pid"] != args["pid"]:
            continue
        if wanted_name and wanted_name not in str(info["name"] or "").lower():
            continue
        if args.get("user", "me") == "me" and args.get("pid") is None and info["username"] != me:
            continue
        procs.append(p)

    for p in procs:  # two-pass CPU sampling
        try:
            p.cpu_percent(None)
        except psutil.Error:
            pass
    time.sleep(0.3)
    rows = []
    for p in procs:
        info = p.info
        try:
            cpu = p.cpu_percent(None)
        except psutil.Error:
            cpu = 0.0
        mem = info["memory_info"].rss if info.get("memory_info") else 0
        row = {
            "pid": info["pid"], "name": info["name"], "user": (info["username"] or "?").split("\\")[-1],
            "cpu": cpu, "mem": mem, "started": info.get("create_time") or 0,
        }
        if args.get("cmdline"):
            try:
                row["cmd"] = fmt.redact(" ".join(p.cmdline()))
            except psutil.Error:
                row["cmd"] = "(not readable)"
        rows.append(row)

    key = {"cpu": lambda r: -r["cpu"], "memory": lambda r: -r["mem"], "name": lambda r: str(r["name"]).lower(),
           "started": lambda r: -r["started"]}[args.get("sort", "memory")]
    rows.sort(key=key)
    cols = ["pid", "name", "user", "cpu %", "memory", "started"] + (["command line"] if args.get("cmdline") else [])
    table_rows = [
        [r["pid"], r["name"], r["user"], f"{r['cpu']:.0f}", fmt.human_bytes(r["mem"]),
         datetime.fromtimestamp(r["started"]).strftime("%m-%d %H:%M") if r["started"] else ""]
        + ([r["cmd"]] if args.get("cmdline") else [])
        for r in rows
    ]
    return fmt.table(cols, table_rows, limit=args["limit"], hint="narrow with name=, pid= or sort=",
                     max_chars=cfg["max_output_chars"], widths={"command line": 200})


# -- services -------------------------------------------------------------------------------

_START = {"auto": "automatic", "manual": "manual", "disabled": "disabled"}


def services(args: dict, cfg: dict) -> str:
    import psutil

    wanted = (args.get("name") or "").lower()
    rows = []
    for s in psutil.win_service_iter():
        try:
            name, display = s.name(), s.display_name()
            if wanted and wanted not in name.lower() and wanted not in display.lower():
                continue
            status = s.status()
            start = _START.get(s.start_type(), s.start_type())
        except psutil.Error:
            continue
        if args.get("status", "all") not in ("all", status):
            continue
        if args.get("start_type", "all") not in ("all", start):
            continue
        detail = {}
        if wanted:  # only look up the expensive details for a narrowed list
            try:
                detail = s.as_dict()
            except psutil.Error:
                detail = {}
        rows.append([name, display, status, start, detail.get("username") or "",
                     fmt.redact(detail.get("binpath") or "")])
    cols = ["name", "display name", "status", "start", "account", "binary"]
    if not wanted:
        cols, rows = cols[:4], [r[:4] for r in rows]
    rows.sort(key=lambda r: r[0].lower())
    return fmt.table(cols, rows, limit=args["limit"], hint="narrow with name= (also shows account and binary)",
                     max_chars=cfg["max_output_chars"], widths={"binary": 140})


# -- disks / network / ports ---------------------------------------------------------------

def disks(args: dict, cfg: dict) -> str:
    import psutil

    rows = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            rows.append([part.device, part.fstype or "", "", "", "not ready"])
            continue
        rows.append([part.device, part.fstype, fmt.human_bytes(usage.total), fmt.human_bytes(usage.free),
                     f"{usage.percent:.0f}% used"])
    return fmt.table(["volume", "filesystem", "size", "free", "use"], rows, limit=100, max_chars=cfg["max_output_chars"])


def network(args: dict, cfg: dict) -> str:
    import socket

    import psutil

    stats, addrs = psutil.net_if_stats(), psutil.net_if_addrs()
    rows = []
    for name, st in stats.items():
        v4 = [a.address for a in addrs.get(name, []) if a.family == socket.AF_INET]
        v6 = [a.address.split("%")[0] for a in addrs.get(name, []) if a.family == socket.AF_INET6 and not a.address.lower().startswith("fe80")]
        mac = [a.address for a in addrs.get(name, []) if a.family == psutil.AF_LINK]
        rows.append([name, "up" if st.isup else "down", f"{st.speed} Mbps" if st.speed else "",
                     ", ".join(v4), ", ".join(v6), mac[0] if mac else ""])
    rows.sort(key=lambda r: (r[1] != "up", r[0].lower()))
    return fmt.table(["adapter", "status", "speed", "IPv4", "IPv6", "MAC"], rows, limit=100,
                     max_chars=cfg["max_output_chars"])


def ports(args: dict, cfg: dict) -> str:
    import psutil

    names: dict[int, str] = {}

    def pname(pid):
        if not pid:
            return ""
        if pid not in names:
            try:
                names[pid] = psutil.Process(pid).name()
            except psutil.Error:
                names[pid] = "?"
        return names[pid]

    wanted = (args.get("process") or "").lower()
    rows, seen = [], set()
    for c in psutil.net_connections(kind="inet"):
        is_listen = c.status == psutil.CONN_LISTEN or (c.type == 2 and not c.raddr)  # 2 = SOCK_DGRAM
        if args.get("listening", True) and not is_listen:
            continue
        proto = "udp" if c.type == 2 else "tcp"
        name = pname(c.pid)
        if wanted and wanted not in name.lower():
            continue
        local = f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else ""
        remote = f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else ""
        key = (proto, local, remote, c.pid)
        if key in seen:
            continue
        seen.add(key)
        rows.append([proto, local, remote, c.status if proto == "tcp" else "", c.pid or "", name])
    rows.sort(key=lambda r: (r[0], int(r[1].rsplit(":", 1)[-1]) if r[1] else 0))
    return fmt.table(["proto", "local", "remote", "state", "pid", "process"], rows, limit=args["limit"],
                     hint="narrow with process= or listening=false", max_chars=cfg["max_output_chars"])


# -- windows ---------------------------------------------------------------------------------

def _is_cloaked(hwnd) -> bool:
    try:
        cloaked = ctypes.c_int(0)
        ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        return bool(cloaked.value)
    except Exception:
        return False


def windows(args: dict, cfg: dict) -> str:
    import psutil
    import win32gui
    import win32process

    found = []

    def visit(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd) or _is_cloaked(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return True
        found.append(hwnd)
        return True

    win32gui.EnumWindows(visit, None)
    wanted = (args.get("process") or "").lower()
    rows = []
    for hwnd in found:
        minimized = bool(win32gui.IsIconic(hwnd))
        if minimized and not args.get("include_minimized"):
            continue
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            pname = psutil.Process(pid).name()
        except psutil.Error:
            pname = "?"
        if wanted and wanted not in pname.lower():
            continue
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        rows.append([win32gui.GetWindowText(hwnd), pname, pid, f"{right - left}x{bottom - top} at {left},{top}",
                     "minimized" if minimized else "normal"])
    return fmt.table(["title", "process", "pid", "size/position", "state"], rows, limit=200,
                     max_chars=cfg["max_output_chars"], widths={"title": 100})


# -- environment -------------------------------------------------------------------------------

def env(args: dict, cfg: dict) -> str:
    scope = args.get("scope", "user")
    if scope == "process":
        items = dict(os.environ)
    elif scope == "user":
        items = _read_values("HKCU\\Environment")
    else:
        items = _read_values("HKLM\\SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment")
    rows = [[k, fmt.mask_value(k, v)] for k, v in sorted(items.items(), key=lambda kv: kv[0].lower())]
    return fmt.table(["name", "value"], rows, limit=500, max_chars=cfg["max_output_chars"], widths={"value": 300})


# -- installed apps -------------------------------------------------------------------------------

_UNINSTALL = (
    ("HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall", "machine"),
    ("HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall", "machine (32-bit)"),
    ("HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall", "user"),
)


def installed_apps(name_filter: str = "") -> list[list]:
    wanted = name_filter.lower()
    rows, seen = [], set()
    for root, scope in _UNINSTALL:
        for sub in _subkeys(root):
            v = _read_values(f"{root}\\{sub}")
            display = str(v.get("DisplayName") or "").strip()
            if not display or v.get("SystemComponent") == 1 or v.get("ParentKeyName"):
                continue
            if wanted and wanted not in display.lower():
                continue
            version = str(v.get("DisplayVersion") or "")
            if (display.lower(), version) in seen:
                continue
            seen.add((display.lower(), version))
            date = str(v.get("InstallDate") or "")
            if len(date) == 8 and date.isdigit():
                date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
            rows.append([display, version, str(v.get("Publisher") or ""), date, scope])
    rows.sort(key=lambda r: r[0].lower())
    return rows


def apps(args: dict, cfg: dict, store_rows: list[list] | None = None) -> str:
    rows = installed_apps(args.get("name") or "")
    if store_rows:
        rows = rows + store_rows
        rows.sort(key=lambda r: r[0].lower())
    return fmt.table(["name", "version", "publisher", "installed", "scope"], rows, limit=args["limit"],
                     hint="narrow with name=", max_chars=cfg["max_output_chars"])


# -- startup ---------------------------------------------------------------------------------------

_RUN_KEYS = (
    ("HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run", "user Run"),
    ("HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\RunOnce", "user RunOnce"),
    ("HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run", "machine Run"),
    ("HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\RunOnce", "machine RunOnce"),
    ("HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Run", "machine Run (32-bit)"),
)
_APPROVED = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StartupApproved\\"


def _approved_state(hive: str, kind: str, name: str) -> str:
    data = _read_values(f"{hive}\\{_APPROVED}{kind}").get(name)
    if isinstance(data, (bytes, bytearray)) and data:
        return "disabled" if data[0] % 2 else "enabled"
    return "enabled"


def startup(args: dict, cfg: dict, task_rows: list[list] | None = None) -> str:
    rows = []
    for path, label in _RUN_KEYS:
        hive = path.split("\\", 1)[0]
        kind = "Run32" if "WOW6432Node" in path else "Run"
        for name, data in _read_values(path).items():
            state = _approved_state(hive, kind, name) if "RunOnce" not in path else "once"
            rows.append([name, label, state, fmt.redact(data)])
    folders = (
        (Path(os.environ.get("APPDATA", "")) / "Microsoft\\Windows\\Start Menu\\Programs\\Startup", "user Startup folder", "HKCU"),
        (Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft\\Windows\\Start Menu\\Programs\\StartUp", "all-users Startup folder", "HKLM"),
    )
    for folder, label, hive in folders:
        try:
            entries = sorted(p for p in folder.iterdir() if p.name.lower() != "desktop.ini")
        except OSError:
            entries = []
        for entry in entries:
            rows.append([entry.name, label, _approved_state(hive, "StartupFolder", entry.name), str(entry)])
    rows.extend(task_rows or [])
    return fmt.table(["name", "where", "state", "command"], rows, limit=200, max_chars=cfg["max_output_chars"],
                     widths={"command": 160})

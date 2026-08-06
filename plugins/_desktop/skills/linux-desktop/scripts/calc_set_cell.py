#!/usr/bin/env python3
"""Set a Calc cell through the visible LibreOffice desktop session."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

for candidate in ("/usr/lib/python3/dist-packages", "/usr/lib/libreoffice/program"):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

try:
    import uno
except Exception as exc:  # pragma: no cover - exercised in the container runtime.
    raise SystemExit(f"LibreOffice UNO is not available: {exc}") from exc


UNO_URL = "uno:socket,host=localhost,port=2002;urp;StarOffice.ComponentContext"
OOXML_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
OOXML_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_PACKAGE_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"m": OOXML_MAIN_NS, "r": OOXML_REL_NS, "rel": REL_PACKAGE_NS}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open an XLSX in visible LibreOffice Calc, edit one cell, save, and verify."
    )
    parser.add_argument("file")
    parser.add_argument("sheet")
    parser.add_argument("cell")
    parser.add_argument("value", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.value:
        parser.error("value is required")
    args.value = " ".join(args.value)
    return args


def run_quiet(command: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=timeout,
    )


def dismiss_document_in_use_dialogs() -> None:
    xdotool = shutil.which("xdotool")
    if not xdotool:
        return
    found = subprocess.run(
        [xdotool, "search", "--onlyvisible", "--name", "Document in Use"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    for window_id in found.stdout.splitlines():
        if window_id.strip():
            run_quiet([xdotool, "windowclose", window_id.strip()], timeout=2)


def connect_once():
    local_ctx = uno.getComponentContext()
    resolver = local_ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver",
        local_ctx,
    )
    return resolver.resolve(os.environ.get("A0_DESKTOP_UNO_URL", UNO_URL))


def desktop_from_context(ctx):
    return ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)


def component_url(component) -> str:
    try:
        return getattr(component, "URL", "") or ""
    except Exception:
        return ""


def component_title(component) -> str:
    try:
        return getattr(component, "Title", "") or ""
    except Exception:
        return ""


def component_has_sheets(component) -> bool:
    try:
        component.getSheets()
        return True
    except Exception:
        return False


def url_to_path(url: str) -> str:
    if not url:
        return ""
    try:
        return os.path.realpath(uno.fileUrlToSystemPath(url))
    except Exception:
        return ""


def find_open_document(desktop, path: Path):
    target_path = os.path.realpath(str(path))
    target_name = path.name
    try:
        enum = desktop.getComponents().createEnumeration()
    except Exception:
        return None
    while enum.hasMoreElements():
        component = enum.nextElement()
        if not component_has_sheets(component):
            continue
        if url_to_path(component_url(component)) == target_path:
            return component
        if target_name and target_name in component_title(component):
            return component
    return None


def libreoffice_command(path: Path) -> list[str]:
    soffice = os.environ.get("SOFFICE") or shutil.which("soffice") or "soffice"
    home = os.environ.get("HOME", "")
    user_installation = f"-env:UserInstallation=file://{home}" if home else ""
    command = [
        soffice,
        "--norestore",
        "--nofirststartwizard",
        "--nolockcheck",
        "--accept=socket,host=localhost,port=2002;urp;StarOffice.ComponentContext",
        "--calc",
        str(path),
    ]
    if user_installation:
        command.insert(4, user_installation)
    return command


def launch_visible_calc(path: Path) -> None:
    subprocess.Popen(
        libreoffice_command(path),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def wait_for_document(path: Path, timeout_seconds: float):
    started = False
    last_error: Exception | None = None
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        dismiss_document_in_use_dialogs()
        try:
            ctx = connect_once()
            desktop = desktop_from_context(ctx)
            document = find_open_document(desktop, path)
            if document is not None:
                return document
            if not started:
                launch_visible_calc(path)
                started = True
        except Exception as exc:
            last_error = exc
            if not started:
                launch_visible_calc(path)
                started = True
        time.sleep(0.5)
    detail = f": {last_error!r}" if last_error else ""
    raise RuntimeError(f"Timed out waiting for LibreOffice Calc to open {path}{detail}")


def focus_document_window(document) -> None:
    try:
        document.CurrentController.Frame.ContainerWindow.setFocus()
    except Exception:
        pass


def sheet_path_for_name(zip_file: zipfile.ZipFile, sheet_name: str) -> str:
    workbook = ET.fromstring(zip_file.read("xl/workbook.xml"))
    rel_id = None
    sheets = workbook.find("m:sheets", NS)
    if sheets is None:
        raise RuntimeError("Workbook has no sheets collection")
    for sheet in sheets:
        if sheet.attrib.get("name") == sheet_name:
            rel_id = sheet.attrib.get(f"{{{OOXML_REL_NS}}}id")
            break
    if not rel_id:
        raise RuntimeError(f"Sheet not found on disk: {sheet_name}")
    rels = ET.fromstring(zip_file.read("xl/_rels/workbook.xml.rels"))
    target = None
    for rel in rels:
        if rel.attrib.get("Id") == rel_id:
            target = rel.attrib.get("Target")
            break
    if not target:
        raise RuntimeError(f"Sheet relationship not found on disk: {sheet_name}")
    target = target.lstrip("/")
    if target.startswith("xl/"):
        return target
    return f"xl/{target}"


def shared_strings(zip_file: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zip_file.namelist():
        return []
    root = ET.fromstring(zip_file.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall("m:si", NS):
        parts = [
            text_node.text or ""
            for text_node in item.iter(f"{{{OOXML_MAIN_NS}}}t")
        ]
        values.append("".join(parts))
    return values


def read_xlsx_cell(path: Path, sheet_name: str, cell_name: str) -> str | None:
    with zipfile.ZipFile(path) as zip_file:
        sheet_path = sheet_path_for_name(zip_file, sheet_name)
        sheet = ET.fromstring(zip_file.read(sheet_path))
        strings = shared_strings(zip_file)
        for cell in sheet.iter(f"{{{OOXML_MAIN_NS}}}c"):
            if cell.attrib.get("r") != cell_name:
                continue
            cell_type = cell.attrib.get("t")
            if cell_type == "inlineStr":
                return "".join(
                    text_node.text or ""
                    for text_node in cell.iter(f"{{{OOXML_MAIN_NS}}}t")
                )
            value_node = cell.find("m:v", NS)
            raw_value = "" if value_node is None or value_node.text is None else value_node.text
            if cell_type == "s" and raw_value != "":
                return strings[int(raw_value)]
            return raw_value
    return None


def wait_for_disk_value(path: Path, sheet: str, cell: str, expected: str) -> str | None:
    latest = None
    for _ in range(24):
        latest = read_xlsx_cell(path, sheet, cell)
        if latest == expected:
            return latest
        time.sleep(0.25)
    return latest


def is_disposed_error(exc: BaseException) -> bool:
    return "DisposedException" in type(exc).__name__ or "DisposedException" in str(exc)


def edit_visible_calc_cell(path: Path, sheet_name: str, cell_name: str, value: str) -> tuple[str, str, str | None]:
    last_error: Exception | None = None
    for _ in range(4):
        document = wait_for_document(
            path,
            timeout_seconds=float(os.environ.get("A0_CALC_OPEN_TIMEOUT", "30")),
        )
        try:
            focus_document_window(document)
            sheets = document.getSheets()
            if not sheets.hasByName(sheet_name):
                raise SystemExit(f"Sheet not found: {sheet_name}")
            sheet = sheets.getByName(sheet_name)
            target_cell = sheet.getCellRangeByName(cell_name)
            before = target_cell.getString()
            target_cell.setString(value)
            document.store()
            after = target_cell.getString()
            disk_value = wait_for_disk_value(path, sheet_name, cell_name, value)
            return before, after, disk_value
        except Exception as exc:
            if not is_disposed_error(exc):
                raise
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"LibreOffice UNO bridge stayed disposed while editing {path}: {last_error!r}")


def main() -> int:
    args = parse_args()
    path = Path(args.file).expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"Workbook not found: {path}")

    before, after, disk_value = edit_visible_calc_cell(path, args.sheet, args.cell, args.value)
    if after != args.value or disk_value != args.value:
        raise SystemExit(
            f"Calc edit verification failed: before={before!r} after={after!r} disk={disk_value!r}"
        )
    print(f"updated {path} {args.sheet}!{args.cell}: {before!r} -> {after!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

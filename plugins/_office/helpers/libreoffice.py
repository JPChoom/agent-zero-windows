from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any


SOFFICE_BINARIES = ("soffice", "libreoffice")
# The Windows LibreOffice installer does not add soffice.exe to PATH by
# default, so shutil.which() alone misses it even when it's installed.
# Check the standard install locations directly as a fallback.
WINDOWS_SOFFICE_CANDIDATES = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
)
CONVERT_TIMEOUT_SECONDS = 45
ODF_MIMETYPES = {
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "odp": "application/vnd.oasis.opendocument.presentation",
}


def find_soffice() -> str:
    for name in SOFFICE_BINARIES:
        path = shutil.which(name)
        if path:
            return path
    if os.name == "nt":
        for candidate in WINDOWS_SOFFICE_CANDIDATES:
            if os.path.isfile(candidate):
                return candidate
    return ""


def collect_status() -> dict[str, Any]:
    soffice = find_soffice()
    status = {
        "ok": True,
        "state": "healthy" if soffice else "missing",
        "healthy": bool(soffice),
        "soffice": soffice,
        "message": "LibreOffice is available." if soffice else "LibreOffice is not installed in this runtime.",
    }
    try:
        from plugins._desktop.helpers import desktop_session

        status["desktop"] = desktop_session.collect_desktop_status()
    except Exception as exc:
        status["desktop"] = {"ok": False, "healthy": False, "error": str(exc)}
    return status


def validate_docx(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.exists():
        return {"ok": False, "error": f"File not found: {source}"}
    try:
        with zipfile.ZipFile(source) as archive:
            archive.getinfo("[Content_Types].xml")
            archive.getinfo("word/document.xml")
    except Exception as exc:
        return {"ok": False, "error": f"DOCX package validation failed: {exc}"}

    soffice = find_soffice()
    if not soffice:
        return {"ok": True, "warning": "LibreOffice binary was not available; package validation only."}

    with tempfile.TemporaryDirectory(prefix="a0-office-validate-") as temp_dir:
        result = _run_soffice(
            soffice,
            [
                "--headless",
                "--safe-mode",
                "--convert-to",
                "pdf",
                "--outdir",
                temp_dir,
                str(source),
            ],
            timeout=CONVERT_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return {"ok": False, "error": _format_process_error(result)}
        return {"ok": True}


def validate_odf(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.exists():
        return {"ok": False, "error": f"File not found: {source}"}
    ext = source.suffix.lower().lstrip(".")
    expected_mimetype = ODF_MIMETYPES.get(ext)
    if not expected_mimetype:
        return {"ok": False, "error": f"Unsupported ODF extension: {ext}"}
    try:
        with zipfile.ZipFile(source) as archive:
            first = archive.infolist()[0]
            mimetype = archive.read("mimetype").decode("utf-8")
            archive.getinfo("content.xml")
            archive.getinfo("META-INF/manifest.xml")
    except Exception as exc:
        return {"ok": False, "error": f"ODF package validation failed: {exc}"}
    if first.filename != "mimetype" or first.compress_type != zipfile.ZIP_STORED:
        return {"ok": False, "error": "ODF mimetype must be the first uncompressed package entry."}
    if mimetype != expected_mimetype:
        return {"ok": False, "error": f"ODF mimetype mismatch: expected {expected_mimetype}, got {mimetype}"}
    return {"ok": True}


def convert_document(path: str | Path, target_format: str, output_dir: str | Path | None = None) -> dict[str, Any]:
    source = Path(path)
    if not source.exists():
        return {"ok": False, "error": f"File not found: {source}"}
    soffice = find_soffice()
    if not soffice:
        return {"ok": False, "error": "LibreOffice is not installed in this runtime."}

    target_format = str(target_format or "").lower().strip().lstrip(".")
    if not target_format:
        return {"ok": False, "error": "target_format is required."}

    destination_dir = Path(output_dir) if output_dir else source.parent
    destination_dir.mkdir(parents=True, exist_ok=True)
    before = {item.name for item in destination_dir.iterdir()} if destination_dir.exists() else set()
    result = _run_soffice(
        soffice,
        [
            "--headless",
            "--safe-mode",
            "--convert-to",
            target_format,
            "--outdir",
            str(destination_dir),
            str(source),
        ],
        timeout=CONVERT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        return {"ok": False, "error": _format_process_error(result)}

    expected = destination_dir / f"{source.stem}.{target_format}"
    if expected.exists():
        return {"ok": True, "path": str(expected)}

    created = [item for item in destination_dir.iterdir() if item.name not in before]
    if created:
        return {"ok": True, "path": str(created[0])}
    return {"ok": False, "error": "LibreOffice completed without producing an output file."}


def _run_soffice(soffice: str, args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "HOME": os.environ.get("HOME") or "/tmp",
        "SAL_USE_VCLPLUGIN": os.environ.get("SAL_USE_VCLPLUGIN") or "gen",
    }
    return subprocess.run(
        [soffice, *args],
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env,
    )


def _format_process_error(result: subprocess.CompletedProcess[str]) -> str:
    details = (result.stderr or result.stdout or "").strip()
    if details:
        return f"LibreOffice exited with {result.returncode}: {details}"
    return f"LibreOffice exited with {result.returncode}."

"""Download llama-server.exe from the official llama.cpp GitHub releases.

Only ever run because the user clicked Download (api/llama_server.py
action=download). Fails closed:
- only assets of github.com/ggml-org/llama.cpp, fetched over HTTPS,
- the asset's SHA-256 must be published by GitHub (the release API's
  `digest` field) and must match the downloaded bytes; no digest = refused,
- the archive must contain llama-server.exe and nothing outside its folder
  (zip-slip check).
Installs into usr/llama-cpp/bin/ and records the release in
usr/llama-cpp/installed.json. llama.cpp is MIT-licensed.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import urllib.request
import zipfile

from helpers import files

RELEASE_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
ALLOWED_DOWNLOAD_PREFIX = "https://github.com/ggml-org/llama.cpp/releases/download/"
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024

# Release asset name patterns per build variant (Windows x64).
VARIANT_PATTERNS = {
    "cuda": [r"^llama-.*-bin-win-cuda-12[\d.]*-x64\.zip$", r"^cudart-llama-bin-win-cuda-12[\d.]*-x64\.zip$"],
    "vulkan": [r"^llama-.*-bin-win-vulkan-x64\.zip$"],
    "cpu": [r"^llama-.*-bin-win-cpu-x64\.zip$"],
}


class DownloadError(Exception):
    pass


def bin_dir() -> str:
    return files.get_abs_path("usr", "llama-cpp", "bin")


def installed_path() -> str:
    return files.get_abs_path("usr", "llama-cpp", "installed.json")


def installed() -> dict | None:
    try:
        with open(installed_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def suggested_variant() -> str:
    return "cuda" if shutil.which("nvidia-smi") else "cpu"


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "agent-zero-windows"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def select_assets(release: dict, variant: str) -> list[dict]:
    patterns = VARIANT_PATTERNS.get(variant)
    if not patterns:
        raise DownloadError(f"Unknown build variant {variant!r}; use cuda, vulkan or cpu.")
    chosen = []
    for pattern in patterns:
        matches = [a for a in release.get("assets", []) if re.match(pattern, str(a.get("name", "")))]
        if not matches:
            raise DownloadError(f"The latest llama.cpp release has no asset matching {pattern}.")
        chosen.append(sorted(matches, key=lambda a: a["name"])[-1])
    for asset in chosen:
        url = str(asset.get("browser_download_url", ""))
        if not url.startswith(ALLOWED_DOWNLOAD_PREFIX):
            raise DownloadError(f"Unexpected download location: {url}")
        digest = str(asset.get("digest") or "")
        if not digest.startswith("sha256:") or len(digest) != len("sha256:") + 64:
            raise DownloadError(f"{asset['name']} has no published SHA-256 digest; refusing to install it unverified.")
        if int(asset.get("size") or 0) > MAX_ARCHIVE_BYTES:
            raise DownloadError(f"{asset['name']} is unexpectedly large.")
    return chosen


def plan(variant: str = "") -> dict:
    """What a download would fetch, without fetching it."""
    variant = variant or suggested_variant()
    release = _get_json(RELEASE_API)
    assets = select_assets(release, variant)
    return {
        "tag": release.get("tag_name", ""),
        "variant": variant,
        "assets": [{"name": a["name"], "size": a.get("size"), "url": a["browser_download_url"], "sha256": a["digest"][7:]} for a in assets],
    }


def _verified_bytes(asset: dict) -> bytes:
    req = urllib.request.Request(asset["url"], headers={"User-Agent": "agent-zero-windows"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = resp.read(MAX_ARCHIVE_BYTES + 1)
    if len(data) > MAX_ARCHIVE_BYTES:
        raise DownloadError(f"{asset['name']} is unexpectedly large.")
    actual = hashlib.sha256(data).hexdigest()
    if actual != asset["sha256"]:
        raise DownloadError(f"{asset['name']}: SHA-256 mismatch (expected {asset['sha256']}, got {actual}).")
    return data


def extract(archives: list[bytes], target: str) -> None:
    """Unpack into a fresh temporary folder, check it, then swap it in."""
    staging = target + ".new"
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging)
    root = os.path.realpath(staging)
    for data in archives:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for member in zf.infolist():
                dest = os.path.realpath(os.path.join(staging, member.filename))
                if not dest.startswith(root + os.sep) and dest != root:
                    raise DownloadError(f"Archive entry escapes its folder: {member.filename}")
            zf.extractall(staging)
    found = [os.path.join(d, "llama-server.exe") for d, _, names in os.walk(staging) if "llama-server.exe" in names]
    if not found:
        raise DownloadError("The archive does not contain llama-server.exe.")
    # Flatten: the folder holding llama-server.exe becomes the bin folder;
    # files at the top of the other archives (the CUDA runtime DLLs) join it.
    source = os.path.dirname(found[0])
    if os.path.realpath(source) != root:
        for name in os.listdir(staging):
            path = os.path.join(staging, name)
            if os.path.isfile(path):
                shutil.move(path, os.path.join(source, name))
    old = target + ".old"
    shutil.rmtree(old, ignore_errors=True)
    if os.path.exists(target):
        os.replace(target, old)
    shutil.move(source, target)
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)


def download(variant: str = "") -> dict:
    """Fetch, verify and install. Only call on an explicit user action."""
    p = plan(variant)
    archives = [_verified_bytes(asset) for asset in p["assets"]]
    extract(archives, bin_dir())
    record = {"tag": p["tag"], "variant": p["variant"], "assets": p["assets"]}
    os.makedirs(os.path.dirname(installed_path()), exist_ok=True)
    with open(installed_path(), "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2)
    return record

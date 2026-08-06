import os
import subprocess
import sys
from pathlib import Path

from helpers import files

FULL_CHROMIUM_PATTERNS = (
    "chromium-*/chrome-linux/chrome",
    "chromium-*/chrome-win/chrome.exe",
)
PLAYWRIGHT_CACHE_ENV = "A0_BROWSER_PLAYWRIGHT_CACHE_DIR"
PLAYWRIGHT_CACHE_DIR = ("tmp", "playwright")
RETIRED_PLAYWRIGHT_CACHE_DIRS = (
    ("usr", "plugins", "_browser", "playwright"),
    ("usr", "browser", "playwright"),
)


def _primary_cache_dir() -> Path:
    override = os.environ.get(PLAYWRIGHT_CACHE_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return Path(files.get_abs_path(*PLAYWRIGHT_CACHE_DIR))


def get_playwright_cache_dir() -> str:
    return str(_primary_cache_dir())


def get_playwright_cache_dirs() -> list[Path]:
    primary = _primary_cache_dir()
    candidates = [primary, *get_retired_playwright_cache_dirs()]
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def get_retired_playwright_cache_dirs() -> list[Path]:
    return [Path(files.get_abs_path(*parts)) for parts in RETIRED_PLAYWRIGHT_CACHE_DIRS]


def configure_playwright_env() -> str:
    cache_dir = get_playwright_cache_dir()
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = cache_dir
    return cache_dir


def find_playwright_binary(cache_dir: Path) -> Path | None:
    for pattern in FULL_CHROMIUM_PATTERNS:
        binary = next(cache_dir.glob(pattern), None)
        if binary and binary.exists():
            return binary
    return None


def get_playwright_binary() -> Path | None:
    return find_playwright_binary(_primary_cache_dir())


def ensure_playwright_binary() -> Path:
    binary = get_playwright_binary()
    if binary:
        return binary

    cache_dir = configure_playwright_env()
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = cache_dir
    install_command = [sys.executable, "-m", "playwright", "install", "chromium"]
    subprocess.check_call(
        install_command,
        env=env,
    )

    binary = get_playwright_binary()
    if not binary:
        raise RuntimeError("Playwright Chromium binary not found after installation")
    return binary

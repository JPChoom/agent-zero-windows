"""The per-user installer (installer/), the dependency lock and the tray launcher.

The installer itself clones from GitHub, so it is exercised up to that point;
the uninstaller runs for real against a fake install and test-only registry
keys (never the real Start menu or Apps entries).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "installer"
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows installer")


def ps(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    # Started from PowerShell 7 (the CI default shell), the inherited
    # PSModulePath hides Windows PowerShell's own modules, so Get-FileHash and
    # friends are "not recognized"; let powershell.exe build its own.
    env = {k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}
    return subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", *args],
                          capture_output=True, text=True, timeout=timeout, env=env)


@pytest.mark.parametrize("script", ["install.ps1", "uninstall.ps1"])
def test_scripts_parse(script):
    path = INSTALLER / script
    result = ps("-Command", f"$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('{path}', [ref]$null, [ref]$e); $e.Count")
    assert result.stdout.strip() == "0", result.stdout + result.stderr


def test_installer_refuses_a_non_release_tag_before_downloading(tmp_path):
    result = ps("-File", str(INSTALLER / "install.ps1"), "-Version", "main; rm -rf /", "-InstallDir", str(tmp_path / "x"))
    out = result.stdout + result.stderr
    if "Python 3.12 not found" in out or "Git not found" in out:
        pytest.skip("this machine lacks the installer's prerequisites")
    assert result.returncode == 1 and "Not a release tag" in out
    assert not (tmp_path / "x").exists()


def _make_shortcut(path: Path, arguments: str, working_dir: str, target: str = r"C:\Windows\notepad.exe") -> None:
    ps("-Command", f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{path}'); $s.TargetPath='{target}';"
                   f"$s.Arguments='{arguments}'; $s.WorkingDirectory='{working_dir}'; $s.Save()")


@pytest.fixture
def fake_install(tmp_path):
    app = tmp_path / "AgentZeroWindows"
    for rel in ("run_ui.py", "agent.py", "helpers/x.py", ".venv/Scripts/python.exe", "usr/settings.json", "usr/memory/m.json"):
        path = app / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    start_menu = tmp_path / "StartMenu"
    start_menu.mkdir()
    _make_shortcut(start_menu / "Agent Zero for Windows.lnk", "", str(app), target=str(app / "AgentZero.exe"))
    test_key = f"HKCU:\\Software\\AgentZeroInstallerTest-{uuid.uuid4().hex[:8]}"
    ps("-Command", f"New-Item -Path '{test_key}\\Uninstall' -Force | Out-Null; New-Item -Path '{test_key}\\Run' -Force | Out-Null;"
                   f"Set-ItemProperty -Path '{test_key}\\Uninstall' -Name InstallLocation -Value '{app}';"
                   f"Set-ItemProperty -Path '{test_key}\\Run' -Name AgentZero -Value 'pythonw.exe \"{app}\\launch.pyw\"';"
                   f"Set-ItemProperty -Path '{test_key}\\Run' -Name OtherApp -Value 'C:\\Other\\other.exe'")
    yield app, start_menu, test_key
    ps("-Command", f"Remove-Item -Path '{test_key}' -Recurse -Force -ErrorAction SilentlyContinue")


def _uninstall(app, start_menu, key, *extra):
    return ps("-File", str(INSTALLER / "uninstall.ps1"), "-InstallDir", str(app), "-Yes",
              "-StartMenuDir", str(start_menu), "-UninstallKey", f"{key}\\Uninstall", "-RunKey", f"{key}\\Run", *extra)


def test_uninstall_keeps_user_data_by_default(fake_install):
    app, start_menu, key = fake_install
    result = _uninstall(app, start_menu, key)
    assert result.returncode == 0, result.stderr
    assert (app / "usr" / "settings.json").exists() and (app / "usr" / "memory" / "m.json").exists()
    assert not (app / "run_ui.py").exists() and not (app / ".venv").exists() and not (app / "helpers").exists()
    assert not (start_menu / "Agent Zero for Windows.lnk").exists()
    run = ps("-Command", f"(Get-ItemProperty -Path '{key}\\Run').PSObject.Properties.Name -join ','").stdout
    assert "OtherApp" in run and "AgentZero" not in run  # only entries pointing at this install
    assert ps("-Command", f"Test-Path '{key}\\Uninstall'").stdout.strip() == "False"


def test_clean_uninstall_removes_everything(fake_install):
    app, start_menu, key = fake_install
    assert _uninstall(app, start_menu, key, "-Clean").returncode == 0
    assert not app.exists()


def test_uninstall_refuses_a_folder_that_is_not_agent_zero(tmp_path):
    other = tmp_path / "Documents"
    other.mkdir()
    (other / "precious.txt").write_text("keep", encoding="utf-8")
    result = ps("-File", str(INSTALLER / "uninstall.ps1"), "-InstallDir", str(other), "-Yes", "-Clean")
    assert result.returncode == 1 and (other / "precious.txt").exists()


def test_lock_matches_every_pin_in_requirements():
    lock = {}
    for line in (ROOT / "requirements.lock.txt").read_text(encoding="utf-8").splitlines():
        if "==" in line and not line.startswith("#"):
            name, version = line.split("==", 1)
            lock[re.sub(r"[-_.]+", "-", name).lower()] = version.strip()
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        spec = line.split("#", 1)[0].strip()
        match = re.match(r"^([A-Za-z0-9._-]+)(?:\[[^\]]+\])?==([^\s;]+)", spec)
        if match:
            name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
            assert lock.get(name) == match.group(2), f"{name}: requirements.txt pins {match.group(2)}, lock has {lock.get(name)}"


def test_lock_never_contains_personal_or_plugin_only_packages():
    text = (ROOT / "requirements.lock.txt").read_text(encoding="utf-8").lower()
    for name in ("yt-dlp", "yt_dlp", "aiogram", "blender"):
        assert name not in text


def test_tray_launcher_shows_and_closes():
    pythonw = Path(sys.executable)
    result = subprocess.run([str(pythonw), str(INSTALLER / "tray_launcher.pyw"), "--no-server", "--smoke"],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


GO = shutil.which("go") or r"C:\Program Files\Go\bin\go.exe"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """AgentZero.exe, Uninstall.exe and the setup .exe, built from source by build.ps1."""
    if not Path(GO).exists():
        pytest.skip("Go is not installed")
    out = tmp_path_factory.mktemp("dist")
    result = ps("-File", str(INSTALLER / "build.ps1"), "-OutDir", str(out), timeout=600)
    assert result.returncode == 0, result.stdout + result.stderr
    return out


def test_setup_exe_carries_the_current_scripts_and_both_programs(built):
    data = (built / "AgentZeroWindows-Setup.exe").read_bytes()
    assert (INSTALLER / "install.ps1").read_bytes() in data
    assert (built / "AgentZero.exe").read_bytes() in data
    assert (built / "Uninstall.exe").read_bytes() in data
    assert (built / "Uninstall.exe").read_bytes().count((INSTALLER / "uninstall.ps1").read_bytes()) == 1


def test_setup_exe_refuses_a_bad_tag_with_exit_code_1(built, tmp_path):
    result = subprocess.run([str(built / "AgentZeroWindows-Setup.exe"), "-version", "main", "-llama", "none",
                             "-dir", str(tmp_path / "x")], capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    out = result.stdout + result.stderr
    if "Python 3.12 not found" in out or "Git not found" in out:
        pytest.skip("this machine lacks the installer's prerequisites")
    assert result.returncode == 1 and "Not a release tag" in out
    assert not (tmp_path / "x").exists()


def test_setup_exe_passes_options_through(built, tmp_path):
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("keep", encoding="utf-8")
    result = subprocess.run([str(built / "AgentZeroWindows-Setup.exe"), "-version", "v1.3", "-llama", "none",
                             "-desktop", "no", "-dir", str(occupied)],
                            capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    out = result.stdout + result.stderr
    if "Python 3.12 not found" in out or "Git not found" in out:
        pytest.skip("this machine lacks the installer's prerequisites")
    assert result.returncode == 1 and "is not an Agent Zero install" in out
    assert (occupied / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_setup_exe_offers_the_desktop_shortcut_option(built):
    result = subprocess.run([str(built / "AgentZeroWindows-Setup.exe"), "-h"], capture_output=True, text=True, timeout=30)
    assert "-desktop" in result.stdout + result.stderr


def test_launcher_has_its_icon_and_shows_in_the_tray_then_closes(built, tmp_path):
    folder = tmp_path / "install"
    folder.mkdir()
    shutil.copy2(built / "AgentZero.exe", folder / "AgentZero.exe")
    assert subprocess.run([str(folder / "AgentZero.exe"), "-icon-check"], timeout=30).returncode == 0
    # A real tray icon on a loaded machine (the whole suite running, or a CI
    # runner) can miss its 30 s window once; a second try tells that from a bug.
    codes = []
    for _ in range(2):
        code = subprocess.run([str(folder / "AgentZero.exe"), "-no-server", "-smoke"], timeout=60).returncode
        codes.append(code)
        if code == 0:
            break
    assert codes[-1] == 0, codes


def _wait_until(condition, seconds=20):
    """Uninstall.exe finishes its cleanup a moment after it returns."""
    import time

    deadline = time.time() + seconds
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.3)
    return condition()


def _installed_with_exes(fake_install, built):
    app, start_menu, key = fake_install
    shutil.copy2(built / "AgentZero.exe", app / "AgentZero.exe")
    shutil.copy2(built / "Uninstall.exe", app / "Uninstall.exe")
    return app, start_menu, key


def test_uninstall_exe_keeps_data_by_default(fake_install, built):
    app, _, _ = _installed_with_exes(fake_install, built)
    result = subprocess.run([str(app / "Uninstall.exe"), "-yes"], capture_output=True, text=True, timeout=120,
                            stdin=subprocess.DEVNULL)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (app / "usr" / "settings.json").exists() and (app / "usr" / "memory" / "m.json").exists()
    assert not (app / "run_ui.py").exists() and not (app / "helpers").exists()
    assert not (app / "AgentZero.exe").exists()
    assert _wait_until(lambda: not (app / "Uninstall.exe").exists())
    assert (app / "usr" / "settings.json").exists()  # the data folder (and so the install folder) stays


def test_uninstall_exe_clean_removes_everything(fake_install, built):
    app, _, _ = _installed_with_exes(fake_install, built)
    result = subprocess.run([str(app / "Uninstall.exe"), "-yes", "-clean"], capture_output=True, text=True, timeout=120,
                            stdin=subprocess.DEVNULL)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _wait_until(lambda: not app.exists())


def test_uninstall_exe_asks_and_a_no_changes_nothing(fake_install, built):
    app, _, _ = _installed_with_exes(fake_install, built)
    result = subprocess.run([str(app / "Uninstall.exe")], input="n\n", capture_output=True, text=True, timeout=120)
    assert result.returncode == 0 and "Nothing was changed" in result.stdout
    assert (app / "run_ui.py").exists() and (app / "usr" / "settings.json").exists()


def test_uninstall_exe_can_delete_data_when_asked(fake_install, built):
    app, _, _ = _installed_with_exes(fake_install, built)
    result = subprocess.run([str(app / "Uninstall.exe")], input="y\ny\n", capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _wait_until(lambda: not app.exists())


def test_uninstall_exe_refuses_a_folder_that_is_not_agent_zero(built, tmp_path):
    other = tmp_path / "Documents"
    other.mkdir()
    (other / "precious.txt").write_text("keep", encoding="utf-8")
    shutil.copy2(built / "Uninstall.exe", other / "Uninstall.exe")
    result = subprocess.run([str(other / "Uninstall.exe"), "-yes", "-clean"], capture_output=True, text=True, timeout=120,
                            stdin=subprocess.DEVNULL)
    assert result.returncode == 1 and (other / "precious.txt").exists()


def test_uninstall_leaves_another_installs_start_menu_entry_and_apps_key(fake_install, tmp_path):
    app, start_menu, key = fake_install
    other = tmp_path / "OtherCopy"
    other.mkdir()
    (other / "run_ui.py").write_text("x", encoding="utf-8")
    # The shortcut and the Apps entry belong to `app`, not to `other`.
    assert _uninstall(other, start_menu, key).returncode == 0
    assert (start_menu / "Agent Zero for Windows.lnk").exists()
    assert ps("-Command", f"Test-Path '{key}\\Uninstall'").stdout.strip() == "True"


def test_uninstall_removes_the_desktop_shortcut_of_this_install(fake_install, tmp_path):
    app, start_menu, key = fake_install
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    link = desktop / "Agent Zero for Windows.lnk"
    _make_shortcut(link, f'"{app}' + r'\installer\tray_launcher.pyw"', str(app))
    assert link.exists()
    assert _uninstall(app, start_menu, key, "-DesktopDir", str(desktop)).returncode == 0
    assert not link.exists()


def test_uninstall_leaves_a_desktop_shortcut_of_another_install(fake_install, tmp_path):
    app, start_menu, key = fake_install
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    link = desktop / "Agent Zero for Windows.lnk"
    _make_shortcut(link, r'"C:\Other\AgentZero\installer\tray_launcher.pyw"', r"C:\Other\AgentZero")
    assert _uninstall(app, start_menu, key, "-DesktopDir", str(desktop)).returncode == 0
    assert link.exists()

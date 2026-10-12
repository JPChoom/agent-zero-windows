# Installer DOX

## Purpose

- Own the per-user Windows installer, uninstaller and tray launcher for Agent Zero for Windows.
- Deliberately limited (v1.4 stage 1): one supported configuration (Windows 11 x64, Python 3.12, Git), one install path (a git checkout of a release tag, so the in-app updater keeps working), one updater (the existing one), clean uninstall.

## Ownership

- `setup.go` (+ `go.mod`) builds `AgentZeroWindows-Setup.exe`: it embeds `install.ps1`, writes it to a temp folder with a UTF-8 BOM, runs it with Windows PowerShell passing `-version`, `-dir`, `-llama`, `-no-shortcut`, `-force` through, returns its exit code, and waits for Enter when double-clicked. Standard library only.
- `build.ps1` builds it with Go into `installer/dist/` (git-ignored) and writes its SHA-256. Rebuild whenever `install.ps1` changes.
- `install.ps1` checks the configuration, clones or updates the chosen release tag into `%LOCALAPPDATA%\Programs\AgentZeroWindows`, creates `.venv`, installs `requirements.lock.txt`, optionally downloads the llama.cpp server (`-Llama ask|auto|cuda|vulkan|rocm|cpu|none`; asks when interactive, skips otherwise; uses the plugin's verified download and switches the plugin on), and adds the Start menu entry and the *Settings > Apps* (HKCU Uninstall) entry.
- `uninstall.ps1` stops processes running from the install, removes the Start menu entry, Run entries that point at the install and the Uninstall entry, and deletes the program; `usr\` is kept unless `-Clean`.
- `tray_launcher.pyw` starts the server hidden (same logic as `plugins/_autostart/launch_agent_zero.pyw`, loaded from it) and shows a tray icon (Open / Settings / Quit), standard library only.
- `agent-zero.ico` is the Start menu, Apps and tray icon.

## Local Contracts

- Never touch an install with local changes, a folder that is not Agent Zero, or anything outside the install and its own registry entries.
- No admin rights, no services, no machine-wide changes.
- Only release tags (`vX.Y` / `vX.Y.Z`) are installed; the tag is validated before any download.
- The uninstaller's test-only parameters (`-StartMenuDir`, `-UninstallKey`, `-RunKey`) exist so tests never touch the real entries.
- The setup `.exe` is not code-signed yet (SmartScreen warns on first run); it installs a published release tag, so an end-to-end run needs a release that contains `installer/`.
- Not yet (needs owner approval): code signing, hash-pinned packages (`pip --require-hashes`), signed release artifacts.

## Verification

- `pytest tests/test_installer.py` (script parsing, tag validation, uninstall against a fake install with test registry keys, the lock, a tray smoke test, and building and running the setup `.exe` when Go is installed).
- On a clean Windows 11 machine: run `install.ps1`, start from the Start menu, use the tray, uninstall (data kept), reinstall into the same place, clean uninstall.

## Child DOX Index

No child DOX files.

# Installer DOX

## Purpose

- Own the per-user Windows installer, `AgentZero.exe` (launcher with tray icon) and `Uninstall.exe` for Agent Zero for Windows.
- Deliberately limited: one supported configuration (Windows 11 x64, Python 3.12, Git), one install path (a git checkout of a release tag, so the in-app updater keeps working), one updater (the existing one), clean uninstall.

## Ownership

- `install.ps1` does the install: checks the configuration, clones or updates the chosen release tag into `%LOCALAPPDATA%\Programs\AgentZeroWindows`, creates `.venv`, installs `requirements.lock.txt` (with a private pip cache), places `AgentZero.exe` and `Uninstall.exe` from `-BundleDir` (and keeps git from listing them), optionally downloads the llama.cpp server (`-Llama ask|auto|cuda|vulkan|rocm|cpu|none`; uses the plugin's verified download and switches the plugin on), adds the Start menu entry, offers a desktop shortcut (`-DesktopShortcut ask|yes|no`) and adds the *Settings > Apps* entry (uninstall string `Uninstall.exe`, or the PowerShell uninstaller without it). Shortcuts start `AgentZero.exe`, or the Python tray launcher when no bundle was given.
- `uninstall.ps1` stops processes running from the install (not `Uninstall.exe`, which waits for it), removes the Start menu and desktop shortcuts and the Apps entry **only when they point at this install**, Run entries that point at it, and the program; `usr\` is kept unless `-Clean`.
- `cmd/setup` builds `AgentZeroWindows-Setup.exe`: embeds `install.ps1`, `AgentZero.exe` and `Uninstall.exe`, unpacks them to a temp folder and runs `install.ps1` with Windows PowerShell (`-version`, `-dir`, `-llama`, `-desktop`, `-no-shortcut`, `-force` pass through); waits for Enter when double-clicked.
- `cmd/launcher` builds `AgentZero.exe` (Windows GUI subsystem): starts the server hidden unless the web UI port already answers, tray icon (left click opens the browser; menu Open / Settings / Quit), one copy only (a second start opens the browser), Quit stops the server it started with everything under it (`taskkill /T`), so no tunnel or llama-server is left behind.
- `cmd/uninstaller` builds `Uninstall.exe`: embeds `uninstall.ps1`, asks (continue? delete your data too? default keep), copies itself to a temp folder to run from there (it cannot delete its own folder), and removes the temp copy, the original and an empty install folder afterwards. `-yes`, `-clean`, `-dir` for unattended use.
- `build.ps1` stages the embedded files into `cmd/*/assets/` (git-ignored), builds launcher, uninstaller, then setup with Go into `dist/` (or `-OutDir`; git-ignored) and writes the setup SHA-256. Rebuild whenever `install.ps1`, `uninstall.ps1`, `agent-zero.ico` or a program changes.
- `tray_launcher.pyw` is the Python equivalent of the launcher for script-only installs. `agent-zero.ico` is the shortcut, Apps and tray icon. All Go code is standard library only.

## Local Contracts

- Never touch an install with local changes, a folder that is not Agent Zero, or anything outside the install and its own shortcuts and registry entries; another copy's shortcuts and Apps entry survive an uninstall.
- No admin rights, no services, no machine-wide changes.
- Only release tags (`vX.Y` / `vX.Y.Z`) are installed; the tag is validated before any download.
- The uninstaller's test-only parameters (`-StartMenuDir`, `-DesktopDir`, `-UninstallKey`, `-RunKey`) exist so tests never touch the real entries; `Uninstall.exe` has none, so its tests use fake installs that nothing registered points at.
- The `.exe` files are not code-signed (SmartScreen warns on first run) and have no embedded icon resource (shortcuts, the tray and Settings > Apps use `agent-zero.ico`). The setup installs a published release tag, so an end-to-end run needs a release that contains `installer/`.
- Not yet (needs owner approval): code signing, hash-pinned packages (`pip --require-hashes`), signed release artifacts.

## Verification

- `pytest tests/test_installer.py` (script parsing, tag validation, shortcut/registry ownership on uninstall, the lock, and - when Go is installed - building all three programs and running them: setup options, launcher icon and tray smoke test, `Uninstall.exe` keep/clean/ask/refuse).
- On a clean Windows 11 machine: run the setup `.exe`, start from the Start menu or desktop shortcut, use the tray, uninstall from Settings > Apps (data kept), reinstall into the same place, clean uninstall.

## Child DOX Index

No child DOX files.

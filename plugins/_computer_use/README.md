# Computer Use

Lets the agent read and operate Windows apps through their **UI Automation** (accessibility) tree, using trycua's open-source [`cua-driver`](https://github.com/trycua/cua) (MIT). Clicks, typing and keys are delivered **in the background**: your mouse does not move and the target window is not brought to the front.

## Install the driver

The driver is a separate, signed program (publisher: Cua AI, Inc.). Agent Zero never downloads it for you.

1. Download `cua-driver-rs-<version>-windows-x86_64-binary.zip` from a `cua-driver-rs-v<version>` release at <https://github.com/trycua/cua/releases>.
2. Check its SHA-256 against the digest shown on the release page (`Get-FileHash <zip>`).
3. Extract it to `usr/cua-driver/<version>/` so that `usr/cua-driver/<version>/cua-driver.exe` exists.

The plugin starts the driver's daemon on first use (`serve --permission-mode standard`, hidden) and turns off the driver's default telemetry first. `computer_use action=stop_driver` stops it.

## Settings (Settings > Agent > Computer Use)

- **Allow input** (off by default): without it the agent can only look (list apps and windows, inspect a window, take screenshots).
- **Driver path**, **Disable driver telemetry**, **Max elements per inspect**.

## Safety

- **Never, in any mode:** sign-in, UAC and password-manager windows (not even read); typing or keys into terminals (use the terminal tool, which the command safety policy checks); lock/log-off/run/security-screen key combinations; typing into fields labelled as passwords, PINs or codes.
- **Asked about outside Bypass:** input into any window the agent did not open in this chat (it may be your unsaved document), foreground delivery (takes focus, moves the real pointer), and window-closing keys (Alt+F4, Ctrl+W, Ctrl+Q). `launch` always asks for a new instance and reports when it attached to one that was already running.
- The chat's permission mode applies first: Plan refuses input, Manual asks.
- `close` only ends apps the agent opened.
- The kill switch blocks input; every input action is written to the audit log first.
- Window text is treated as untrusted outside content.

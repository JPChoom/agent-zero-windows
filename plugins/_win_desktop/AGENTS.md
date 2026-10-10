# Windows Desktop Plugin DOX

## Purpose

- Own the Windows Desktop surface: the agent's screenshot/control tools for the real Windows desktop and the live viewer panel that streams it.
- Windows only (`os_support: windows`); the Linux Xpra desktop is `plugins/_desktop`. Each registers its own surface, so only one Desktop appears in the rail.

## Ownership

- `helpers/capture.py` owns screen grabs (PIL `ImageGrab`), monitor listing, cursor compositing, scaling and JPEG encoding (`prepare_image` + `encode_image`, composed by `capture_frame`), plus config resolution (`get_config`, whose `_DEFAULTS` must match `default_config.yaml`).
- `helpers/stream_hub.py` owns the shared capture loop: one producer thread per stream setting for all viewers, unchanged-frame skipping, idle slowdown, keepalive frames, poke on viewer input, below-normal thread priority.
- `helpers/input_control.py` owns SendInput mouse/keyboard, window focus/listing, clipboard. It performs no permission checks itself.
- `api/desktop_stream.py` owns the MJPEG viewer stream (GET, auth required, no CSRF because an `<img>` cannot send one; read-only) and the `?monitors=1` monitor list.
- `api/desktop_input.py` owns viewer input from the signed-in user (auth + CSRF).
- `tools/desktop_screenshot.py` and `tools/desktop_control.py` own the agent-facing tools; `prompts/` their prompts.
- `webui/` owns the panel, store and modal; `extensions/webui/` registers the `win-desktop` surface and right-canvas panel.

## Local Contracts

- Input is off by default (`control_enabled: false`). Every input path (agent tool and viewer endpoint) enforces the same three gates itself: `control_enabled`, the kill switch (`helpers/kill_switch.py`), and an audit record written before acting. Clipboard/typed text is never copied into the audit log.
- Viewing and controlling stay separate: the stream never accepts input; input goes only through `desktop_input` or the agent tool.
- Viewer coordinates arrive in streamed-frame space and are scaled back with the reported frame size and the chosen monitor's offset.
- Streams are bounded (`STREAM_SECONDS`) so an abandoned tab frees its worker; each part is followed immediately by the next boundary so a browser shows a frame even when the next one is seconds away.
- Change detection compares the scaled image (what the viewer sees); the loop drops to `IDLE_FPS` after `IDLE_AFTER` seconds without change, re-sends an unchanged frame every `KEEPALIVE_SECONDS`, and stops `LINGER_SECONDS` after its last viewer leaves.
- No capture or codec dependency beyond PIL without owner approval (DXGI, H.264 etc. are roadmap items that need a measured baseline first).
- Ctrl+Alt+Del, UAC prompts and the lock screen run on the secure desktop and cannot be captured or driven from this user process.

## Work Guidance

- Measure before claiming performance: record grab/resize/encode times and frames sent (measured 2026-10-10 on a three-monitor 5760x1080 desktop: grab ~66 ms, resize to 1920 px ~24 ms, encode ~3 ms, ~55 KB per frame; a busy desktop changes ~0.3% of pixels between grabs, so it rarely counts as idle).

## Verification

- `pytest tests/test_win_desktop_capture.py tests/test_win_desktop_stream_hub.py tests/test_win_desktop_viewer.py tests/test_win_desktop_input.py tests/test_win_desktop_control_gates.py`
- Smoke-test the Desktop surface on Windows: stream starts, monitor selector works, view-only by default, input works only with `control_enabled`.

## Child DOX Index

No child DOX files.

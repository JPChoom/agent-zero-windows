# Color Picker Component DOX

## Purpose

- Own the shared, themed color picker popover that replaces the OS dialog opened by `<input type="color">`.

## Ownership

- `color-picker-store.js` owns the `colorPicker` store: open/close, HSV state, hex parsing, viewport positioning, and the `hexToHsv`/`hsvToHex` helpers.
- `color-picker.html` owns the popover markup (saturation/value square, hue bar, hex field, optional swatches) and its styles. It is mounted once in `webui/index.html`.

## Local Contracts

- Callers open it with `$store.colorPicker.open(anchorEl, { value, onChange, title, swatches })`; do not mount extra instances.
- `onChange(hex)` fires live while dragging with lowercase `#rrggbb`; Escape reverts to the opening value, Enter/outside click keeps the current value.
- The popover stays above modals (`z-index: 12000`) and inside the viewport.
- Do not reintroduce `<input type="color">` for theme colors; use this picker so the UI stays in theme.

## Work Guidance

- Style with theme tokens (`--s2`, `--line-strong`, `--t0`, `--radius-lg`) with `--color-*` fallbacks.

## Verification

- Smoke-test opening from the sidebar Preferences and Settings > Appearance, dragging both controls, typing a hex value, Escape revert, and outside-click close.

## Child DOX Index

No child DOX files.

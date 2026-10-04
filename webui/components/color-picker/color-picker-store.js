import { createStore } from "/js/AlpineStore.js";

// Shared, themed color picker popover (replaces the OS color dialog that
// <input type="color"> opens). One instance, mounted in index.html;
// callers open it next to their swatch:
//   $store.colorPicker.open($el, { value: "#4a8cff", onChange: (hex) => ... })
// onChange fires live while the user drags; Escape restores the opening
// value, Enter/outside click keeps the current one.

const HEX_RE = /^#?([0-9a-f]{6})$/i;
const POPOVER_WIDTH = 248;
const POPOVER_HEIGHT = 286;
const GAP = 8;

export function hexToHsv(hex) {
  const m = HEX_RE.exec(String(hex || "").trim());
  if (!m) return { h: 210, s: 0.7, v: 1 };
  const n = parseInt(m[1], 16);
  const r = ((n >> 16) & 255) / 255;
  const g = ((n >> 8) & 255) / 255;
  const b = (n & 255) / 255;
  const max = Math.max(r, g, b);
  const d = max - Math.min(r, g, b);
  let h = 0;
  if (d) {
    if (max === r) h = ((g - b) / d) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h = (h * 60 + 360) % 360;
  }
  return { h, s: max ? d / max : 0, v: max };
}

export function hsvToHex({ h, s, v }) {
  const f = (k) => {
    const x = (k + h / 60) % 6;
    return v - v * s * Math.max(0, Math.min(x, 4 - x, 1));
  };
  const to = (c) => Math.round(c * 255).toString(16).padStart(2, "0");
  return `#${to(f(5))}${to(f(3))}${to(f(1))}`;
}

const model = {
  isOpen: false,
  title: "",
  swatches: [],
  h: 210,
  s: 0.7,
  v: 1,
  hexInput: "",
  top: 0,
  left: 0,
  _initial: "",
  _onChange: null,
  _anchor: null,

  get hex() {
    return hsvToHex(this);
  },

  get hueColor() {
    return hsvToHex({ h: this.h, s: 1, v: 1 });
  },

  open(anchor, { value = "", onChange = null, title = "", swatches = [] } = {}) {
    const hsv = hexToHsv(value);
    this.h = hsv.h;
    this.s = hsv.s;
    this.v = hsv.v;
    this._initial = HEX_RE.test(value) ? `#${HEX_RE.exec(value)[1].toLowerCase()}` : "";
    this.hexInput = this.hex;
    this._onChange = typeof onChange === "function" ? onChange : null;
    this._anchor = anchor || null;
    this.title = title;
    this.swatches = Array.isArray(swatches) ? swatches.filter((c) => HEX_RE.test(c)) : [];
    this._position();
    this.isOpen = true;
  },

  close({ revert = false } = {}) {
    if (!this.isOpen) return;
    if (revert && this._initial) this._onChange?.(this._initial);
    this.isOpen = false;
    this._onChange = null;
    this._anchor = null;
  },

  // Called from pointer handlers on the saturation/value square and the
  // hue bar; x/y are 0..1 within the element.
  setSV(x, y) {
    this.s = Math.min(1, Math.max(0, x));
    this.v = Math.min(1, Math.max(0, 1 - y));
    this._emit();
  },

  setHue(x) {
    this.h = Math.min(359.9, Math.max(0, x * 360));
    this._emit();
  },

  commitHexInput() {
    const m = HEX_RE.exec(this.hexInput.trim());
    if (!m) {
      this.hexInput = this.hex;
      return;
    }
    const hsv = hexToHsv(m[1]);
    this.h = hsv.h;
    this.s = hsv.s;
    this.v = hsv.v;
    this._emit();
  },

  pick(hex) {
    const hsv = hexToHsv(hex);
    this.h = hsv.h;
    this.s = hsv.s;
    this.v = hsv.v;
    this._emit();
  },

  // Drag helper: tracks the pointer on `el` and feeds fractions to `apply`.
  drag(event, el, apply) {
    event.preventDefault();
    const update = (e) => {
      const r = el.getBoundingClientRect();
      apply((e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height);
    };
    update(event);
    const move = (e) => update(e);
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  },

  _emit() {
    const hex = this.hex;
    this.hexInput = hex;
    this._onChange?.(hex);
  },

  // Open beside the anchor, flipped/clamped to stay inside the viewport.
  _position() {
    const vw = document.documentElement.clientWidth;
    const vh = document.documentElement.clientHeight;
    const r = this._anchor?.getBoundingClientRect?.();
    if (!r) {
      this.left = Math.max(GAP, (vw - POPOVER_WIDTH) / 2);
      this.top = Math.max(GAP, (vh - POPOVER_HEIGHT) / 2);
      return;
    }
    let top = r.bottom + GAP;
    if (top + POPOVER_HEIGHT > vh - GAP) top = r.top - POPOVER_HEIGHT - GAP;
    this.top = Math.min(Math.max(GAP, top), vh - POPOVER_HEIGHT - GAP);
    this.left = Math.min(Math.max(GAP, r.left), vw - POPOVER_WIDTH - GAP);
  },
};

export const store = createStore("colorPicker", model);

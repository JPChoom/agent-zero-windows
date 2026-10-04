/**
 * Permission mode selector state.
 *
 * The mode is per chat and lives on the server, in memory only
 * (plugins/_permissions/helpers/mode_state.py): every chat starts at the
 * default mode, and a restart resets all of them. This store tracks the
 * mode of whichever chat is selected (globalThis.getContext()) and re-reads
 * it when the selection changes (sync() runs every second while the
 * selector is mounted).
 *
 * Bypass requires a separate password, entered in bypass-unlock.html.
 *
 * Registered through createStore rather than a hand-rolled alpine:init
 * listener. createStore registers immediately when Alpine is already
 * running and defers only when it is not; a bare alpine:init listener
 * covers just the second case, so the store silently failed to exist
 * whenever this module loaded after Alpine had started - which is what
 * happens for a plugin extension.
 */
import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import { openModal, closeModal } from "/js/modals.js";

export const UNLOCK_MODAL = "/plugins/_permissions/webui/bypass-unlock.html";

export const store = createStore("permissionsMode", {
  mode: "manual",
  modes: [],
  ctxid: null,
  bypassUntil: 0,
  passwordSet: false,
  open: false,
  loading: false,
  loaded: false,
  now: Date.now() / 1000,

  // Unlock modal state - cleared whenever the modal closes.
  unlockError: "",
  unlocking: false,

  currentContext() {
    return typeof globalThis.getContext === "function" ? globalThis.getContext() : null;
  },

  async refresh() {
    const ctxid = this.currentContext();
    try {
      const data = await callJsonApi("permissions_mode", { ctxid });
      if (data?.ok) {
        this.ctxid = ctxid;
        this.mode = data.mode || "manual";
        this.bypassUntil = data.bypass_until || 0;
        this.modes = data.modes || this.modes;
        this.passwordSet = !!data.bypass_password_set;
        this.loaded = true;
      }
    } catch (error) {
      // The selector keeps showing its last known value; a failed read
      // must not break the input box it sits under.
      console.error("permissions: could not read mode", error);
    }
  },

  // Called every second while the selector is mounted.
  sync() {
    this.now = Date.now() / 1000;
    if (this.loading) return;
    const ctxChanged = this.currentContext() !== this.ctxid;
    const bypassEnded = this.mode === "bypass" && this.bypassUntil && this.now >= this.bypassUntil;
    if (!this.loaded || ctxChanged || bypassEnded) {
      this.loading = true;
      this.refresh().finally(() => (this.loading = false));
    }
  },

  label() {
    const found = this.modes.find((m) => m.id === this.mode);
    return found ? found.label : titleCase(this.mode);
  },

  color() {
    const found = this.modes.find((m) => m.id === this.mode);
    return found ? found.color : "var(--color-text-muted)";
  },

  bypassRemaining() {
    if (this.mode !== "bypass" || !this.bypassUntil) return "";
    const secs = Math.max(0, Math.round(this.bypassUntil - this.now));
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  },

  async select(id) {
    this.open = false;
    if (id === this.mode) return;
    if (!this.currentContext()) {
      globalThis.toastFrontendWarning?.("Open a chat first - the mode applies to one chat.", "Permissions");
      return;
    }
    if (id === "bypass") {
      this.unlockError = "";
      openModal(UNLOCK_MODAL).then(() => {
        this.unlockError = "";
        this.unlocking = false;
      });
      return;
    }
    await this._apply({ mode: id });
  },

  async unlock(password) {
    if (this.unlocking) return;
    this.unlocking = true;
    this.unlockError = "";
    try {
      const ok = await this._apply({ mode: "bypass", password }, { quietErrors: true });
      if (ok) closeModal(UNLOCK_MODAL);
    } finally {
      this.unlocking = false;
    }
  },

  async _apply(payload, { quietErrors = false } = {}) {
    const ctxid = this.currentContext();
    try {
      const data = await callJsonApi("permissions_mode", { ctxid, ...payload });
      if (!data?.ok) {
        const message = data?.error || "Could not change mode";
        if (quietErrors) this.unlockError = message;
        else globalThis.toastFrontendError?.(message, "Permissions");
        return false;
      }
      this.ctxid = ctxid;
      this.mode = data.mode;
      this.bypassUntil = data.bypass_until || 0;
      globalThis.justToast?.(`Permission mode: ${this.label()}`, "success", 1500, "perm-mode");
      return true;
    } catch (error) {
      const message = error?.message || "Could not change mode";
      if (quietErrors) this.unlockError = message;
      else globalThis.toastFrontendError?.(message, "Permissions");
      return false;
    }
  },
});

function titleCase(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/^\w/, (c) => c.toUpperCase());
}

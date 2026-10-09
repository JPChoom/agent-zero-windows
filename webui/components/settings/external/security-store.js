import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";

// Settings > Security. The allowlist is saved through its own endpoint
// (api/security_settings.py) because a remote change that would lock the
// user out needs the Bypass password; the result is mirrored into
// $store.settings so the main Save button doesn't write back a stale copy.
export const store = createStore("securitySettings", {
  loaded: false,
  busy: false,
  allowlist: "",
  enabled: true,
  invalid: [],
  blocked: [],
  isLocal: true,
  myIp: "",
  bypassPasswordSet: false,
  error: "",

  async load() {
    try {
      this._apply(await callJsonApi("security_settings", { action: "get" }));
      this.loaded = true;
    } catch (e) {
      this.error = e?.message || "Could not load security settings";
    }
  },

  _apply(data) {
    if (!data?.ok) return;
    this.allowlist = data.allowlist || "";
    this.enabled = !!data.enabled;
    this.invalid = data.invalid || [];
    this.blocked = data.blocked || [];
    this.isLocal = !!data.is_local;
    this.myIp = data.my_ip || "";
    this.bypassPasswordSet = !!data.bypass_password_set;
    const s = globalThis.Alpine?.store?.("settings")?.settings;
    if (s) {
      s.tunnel_ip_allowlist = this.allowlist;
      s.tunnel_allowlist_enabled = this.enabled;
    }
  },

  // Set when the server asks for the Bypass password to confirm a change;
  // the UI then shows a masked field and calls confirmWithPassword().
  pendingPayload: null,
  pendingMessage: "",

  async confirmWithPassword(password) {
    if (!this.pendingPayload) return false;
    const payload = this.pendingPayload;
    const message = this.pendingMessage;
    return this._call({ ...payload, password }, message);
  },

  cancelPending() {
    this.pendingPayload = null;
    this.pendingMessage = "";
    this.error = "";
  },

  async _call(payload, okMessage) {
    this.busy = true;
    this.error = "";
    try {
      const data = await callJsonApi("security_settings", payload);
      if (!data?.ok) {
        this.error = data?.error || "Save failed";
        if (data?.needs_password) {
          const { password, ...rest } = payload;
          this.pendingPayload = rest;
          this.pendingMessage = okMessage;
        }
        return false;
      }
      this.pendingPayload = null;
      this.pendingMessage = "";
      this._apply(data);
      globalThis.toastFrontendSuccess?.(okMessage, "Security");
      return true;
    } catch (e) {
      this.error = e?.message || "Save failed";
      return false;
    } finally {
      this.busy = false;
    }
  },

  saveAllowlist() {
    return this._call(
      { action: "save_allowlist", text: this.allowlist, enabled: this.enabled },
      "Tunnel allowlist saved"
    );
  },

  allowIp(ip) {
    return this._call({ action: "allow_ip", ip }, `${ip} added to the allowlist`);
  },

  logFilter: "logins",
  logRecords: [],
  logLoading: false,
  logOpen: null,
  logFilterTried: false,

  async loadLog() {
    this.logLoading = true;
    this.logFilterTried = true;
    try {
      const data = await callJsonApi("security_settings", { action: "audit_log", filter: this.logFilter, limit: 200 });
      this.logRecords = data?.ok ? data.records || [] : [];
      this.logOpen = null;
    } catch (e) {
      globalThis.toastFrontendError?.(e?.message || "Could not load the access log", "Security");
    } finally {
      this.logLoading = false;
    }
  },

  eventLabel(event) {
    return {
      login_success: "Signed in",
      login_failure: "Sign-in failed",
      login_locked: "Locked out",
      logout: "Signed out",
      remote_access: "Remote visit",
      blocked: "Blocked",
    }[event] || event;
  },

  eventTone(event) {
    if (event === "login_success" || event === "logout" || event === "remote_access") return "ok";
    if (event === "blocked" || event === "login_failure" || event === "login_locked") return "bad";
    return "info";
  },

  shortAgent(ua) {
    if (!ua) return "";
    const browser = (ua.match(/(Edg|OPR|Chrome|Firefox|Safari)\/[\d.]+/) || [""])[0].replace("Edg", "Edge").replace("OPR", "Opera");
    const os = (ua.match(/Windows NT [\d.]+|Android [\d.]+|iPhone OS [\d_]+|Mac OS X [\d_]+|Linux/) || [""])[0];
    return [browser, os].filter(Boolean).join(" · ") || ua.slice(0, 60);
  },
});

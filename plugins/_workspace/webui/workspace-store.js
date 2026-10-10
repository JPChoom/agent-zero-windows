import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";

// Agent Workspace view (api/workspace.py, helpers/workspace.py): which agent
// owns which apps, terminals and browser tabs.

const POLL_MS = 4000;
const KIND_ICONS = { app: "apps", terminal: "terminal", browser: "language" };
const KIND_NAMES = { app: "Apps", terminal: "Terminals", browser: "Browser tabs" };

export const store = createStore("workspace", {
  resources: [],
  contexts: {},
  controlEnabled: false,
  loaded: false,
  error: "",
  filter: "all",
  onlyThisChat: false,
  confirm: null,
  busy: false,
  _timer: null,

  // --- lifecycle -------------------------------------------------------------
  onMount() {
    this.refresh();
    this.onUnmount();
    this._timer = setInterval(() => {
      if (!document.hidden) this.refresh(true);
    }, POLL_MS);
  },

  onUnmount() {
    if (this._timer) clearInterval(this._timer);
    this._timer = null;
  },

  async api(action, payload = {}) {
    const result = await callJsonApi("workspace", { action, ...payload });
    if (!result?.ok) throw new Error(result?.error || "The Workspace request failed.");
    this._apply(result);
    return result;
  },

  _apply(state) {
    this.resources = state.resources || [];
    this.contexts = state.contexts || {};
    this.controlEnabled = Boolean(state.control_enabled);
    this.loaded = true;
    this.error = "";
  },

  async refresh(quiet = false) {
    try {
      await this.api("list");
    } catch (error) {
      if (!quiet) this.error = error.message;
    }
  },

  // --- view ----------------------------------------------------------------------
  get currentChat() {
    try {
      return globalThis.getContext?.() || "";
    } catch {
      return "";
    }
  },

  get filters() {
    return [{ id: "all", label: "All" }, ...Object.entries(KIND_NAMES).map(([id, label]) => ({ id, label }))];
  },

  get visible() {
    return this.resources.filter(
      (r) =>
        (this.filter === "all" || r.kind === this.filter) &&
        (!this.onlyThisChat || r.owner_context === this.currentChat),
    );
  },

  // Orphaned apps (their chat is gone) first, then one group per chat, the current chat on top.
  get groups() {
    const groups = new Map();
    for (const item of this.visible) {
      const orphan = item.state === "orphaned";
      const key = orphan ? "orphaned" : item.owner_context || "none";
      if (!groups.has(key)) {
        groups.set(key, {
          key,
          orphan,
          current: !orphan && key === this.currentChat,
          title: orphan ? "Apps whose chat was deleted" : this.contexts[key] || "Chat",
          items: [],
        });
      }
      groups.get(key).items.push(item);
    }
    const rank = (g) => (g.orphan ? 0 : g.current ? 1 : 2);
    return [...groups.values()].sort((a, b) => rank(a) - rank(b) || a.title.localeCompare(b.title));
  },

  get summary() {
    const count = (kind) => this.visible.filter((r) => r.kind === kind).length;
    const part = (n, one, many) => `${n} ${n === 1 ? one : many}`;
    return [part(count("app"), "app", "apps"), part(count("terminal"), "terminal", "terminals"), part(count("browser"), "browser tab", "browser tabs")].join("   ");
  },

  icon(item) {
    return KIND_ICONS[item.kind] || "deployed_code";
  },

  age(item) {
    if (!item.created_at) return "";
    const seconds = Math.max(0, Date.now() / 1000 - item.created_at);
    if (seconds < 90) return "just now";
    if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
    if (seconds < 172800) return `${Math.round(seconds / 3600)} h`;
    return `${Math.round(seconds / 86400)} d`;
  },

  canAdopt(item) {
    return item.kind === "app" && Boolean(this.currentChat) && (item.owner_context !== this.currentChat || item.state === "orphaned");
  },

  // --- actions ---------------------------------------------------------------------
  async run(label, action, payload) {
    this.busy = true;
    try {
      await this.api(action, payload);
    } catch (error) {
      window.toastFrontendError?.(error.message, label);
    } finally {
      this.busy = false;
    }
  },

  adopt(item) {
    return this.run("Workspace", "adopt", { id: item.id, context_id: this.currentChat });
  },

  askRelease(item) {
    this.confirm = {
      title: "Stop tracking this app?",
      message: `${item.label} keeps running. Agents will treat it as your own app: they must ask before typing into it and cannot close it.`,
      okLabel: "Stop tracking",
      danger: false,
      run: () => this.run("Workspace", "release", { id: item.id }),
    };
  },

  askClose(item) {
    const what = item.kind === "terminal" ? "terminal session" : "app";
    this.confirm = {
      title: `Close this ${what}?`,
      message:
        item.kind === "terminal"
          ? `Ends ${item.label} (${item.detail || "no folder"}). Programs started from it may keep running.`
          : `Ends ${item.label}. Anything you haven't saved in it is lost.`,
      okLabel: "Close",
      danger: true,
      run: () => this.run("Workspace", "close", { id: item.id }),
    };
  },

  async confirmOk() {
    const action = this.confirm?.run;
    this.confirm = null;
    await action?.();
  },
});

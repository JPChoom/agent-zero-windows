import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";

// Child agents panel (plugins/_child_agents/api/status.py, helpers/child_agents.py):
// what each child agent of this chat is doing, live.

const POLL_MS = 3000;

export const store = createStore("childAgents", {
  parent: null,
  current: "",
  children: [],
  now: 0,
  loaded: false,
  error: "",
  busy: false,
  _timer: null,

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

  get chat() {
    try {
      return globalThis.getContext?.() || "";
    } catch {
      return "";
    }
  },

  async call(payload = {}) {
    const result = await callJsonApi("/plugins/_child_agents/status", { context_id: this.chat, ...payload });
    this.parent = result.parent || null;
    this.current = result.current || "";
    this.children = result.children || [];
    this.now = result.now || Date.now() / 1000;
    this.loaded = true;
    this.error = result.ok === false ? result.error || "The request failed." : "";
    return result;
  },

  async refresh(quiet = false) {
    try {
      await this.call();
    } catch (error) {
      if (!quiet) this.error = error.message || "Could not load the child agents.";
    }
  },

  async stop(child) {
    if (this.busy) return;
    this.busy = true;
    try {
      await this.call({ action: "stop", name: child.name });
    } catch (error) {
      this.error = error.message || "Could not stop it.";
    } finally {
      this.busy = false;
    }
  },

  async open(id) {
    const chats = globalThis.Alpine?.store?.("chats");
    if (chats?.selectChat && id) await chats.selectChat(id);
    this.refresh(true);
  },

  // --- view -----------------------------------------------------------------------
  get isChild() {
    return Boolean(this.parent && this.current && this.parent.id !== this.current);
  },

  stateIcon(child) {
    return { running: "progress_activity", idle: "check_circle", gone: "link_off" }[child.state] || "help";
  },

  stateText(child) {
    return { running: "Working", idle: "Idle", gone: "Chat deleted" }[child.state] || child.state;
  },

  age(child) {
    const at = child.activity?.last_activity || 0;
    if (!at) return "";
    const seconds = Math.max(0, Math.round(this.now - at));
    if (seconds < 5) return "just now";
    if (seconds < 90) return seconds + " s ago";
    if (seconds < 5400) return Math.round(seconds / 60) + " min ago";
    return Math.round(seconds / 3600) + " h ago";
  },

  detail(child) {
    const parts = [];
    const steps = child.activity?.steps || 0;
    if (steps) parts.push(steps + (steps === 1 ? " step" : " steps"));
    const age = this.age(child);
    if (age) parts.push((child.state === "running" ? "active " : "last activity ") + age);
    return parts.join(" · ");
  },

  worktreeLabel(child) {
    const tree = (child.worktrees || [])[0];
    return tree ? tree.branch : "";
  },

  worktreeTitle(child) {
    const tree = (child.worktrees || [])[0];
    return tree ? "Works in its own git worktree: " + tree.path + " (from " + tree.repo + "). The parent reviews it with coding_task diff / merge and the child argument." : "";
  },
});

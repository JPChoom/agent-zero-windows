import { createStore } from "/js/AlpineStore.js";
import * as API from "/js/api.js";
import { closeModal } from "/js/modals.js";
import { store as chatsStore } from "/components/sidebar/chats/chats-store.js";
import {
  toastFrontendError,
  toastFrontendInfo,
} from "/components/notifications/notification-store.js";

const LEARNED_API = "/plugins/_skills/learned_skills";

function minutes(seconds) {
  if (seconds == null) return "";
  if (seconds < 90) return `${Math.round(seconds)} s`;
  return `${(seconds / 60).toFixed(1)} min`;
}

function day(ts) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleDateString();
}

const model = {
  skills: [],
  settings: null,
  filter: "all", // all | review | active | disabled
  loading: false,
  busy: "",
  editing: "", // name of the skill open in the editor
  editText: "",
  editState: "",

  async onOpen() {
    this.editing = "";
    await this.load();
  },

  cleanup() {
    this.editing = "";
    this.editText = "";
  },

  async call(action, extra = {}) {
    const response = await API.callJsonApi(LEARNED_API, { action, ...extra });
    if (!response?.ok) throw new Error(response?.error || "Failed");
    return response;
  },

  async load() {
    this.loading = true;
    try {
      const response = await this.call("list");
      this.skills = response.skills || [];
      this.settings = response.settings || null;
    } catch (error) {
      await toastFrontendError(error?.message || "Failed to load learned skills", "Learned skills");
    } finally {
      this.loading = false;
    }
  },

  count(state) {
    return this.skills.filter((s) => state === "all" || s.state === state).length;
  },

  get visible() {
    return this.skills.filter((s) => this.filter === "all" || s.state === this.filter);
  },

  badge(skill) {
    return { active: "Active", review: "Needs a look", disabled: "Turned off" }[skill.state] || skill.state;
  },

  origin(skill) {
    return skill.learned_by === "auto" ? "Learned on its own" : "Learned when asked";
  },

  // "Learned from a 6.2 min, 14-step task · used 3x, on average 1.4 min, 4 steps · last used 11/2/2026"
  statsLine(skill) {
    const parts = [];
    if (skill.learned) parts.push(`Learned from a ${minutes(skill.learned.seconds)}, ${skill.learned.steps}-step task`);
    if (skill.uses) {
      parts.push(`used ${skill.uses}x, on average ${minutes(skill.avg_seconds)}, ${skill.avg_steps} steps`);
      parts.push(`last used ${day(skill.last_used)}`);
    } else if (skill.state === "active") {
      parts.push("not used yet");
    }
    return parts.join(" · ");
  },

  // How much faster later uses were than the task that taught the skill.
  speedup(skill) {
    if (!skill.learned || !skill.uses || !skill.avg_seconds) return "";
    const ratio = skill.learned.seconds / skill.avg_seconds;
    if (ratio >= 1.15) return `${ratio.toFixed(1)}x faster`;
    if (ratio <= 0.87) return "not faster";
    return "about the same";
  },

  reviewLine(skill) {
    const sources = skill.review?.sources || [];
    return sources.length ? `The task read ${sources.join(", ")}. Check the steps before approving.` : "";
  },

  async act(skill, action, extra = {}, message = "") {
    this.busy = skill.name;
    try {
      await this.call(action, { name: skill.name, ...extra });
      if (message) await toastFrontendInfo(message, "Learned skills");
      if (this.editing === skill.name && action !== "save") this.editing = "";
      await this.load();
    } catch (error) {
      await toastFrontendError(error?.message || "Failed", "Learned skills");
    } finally {
      this.busy = "";
    }
  },

  approve(skill) { return this.act(skill, "approve", {}, `${skill.name} is now active.`); },
  discard(skill) { return this.act(skill, "discard", {}, `${skill.name} was discarded.`); },
  disable(skill) { return this.act(skill, "disable", {}, `${skill.name} is turned off.`); },
  enable(skill) { return this.act(skill, "enable", {}, `${skill.name} is active again.`); },
  remove(skill) { return this.act(skill, "delete", {}, `${skill.name} was deleted.`); },
  restore(skill, version) {
    return this.act(skill, "restore", { version }, `${skill.name}: version ${version} restored.`);
  },

  async edit(skill) {
    if (this.editing === skill.name) {
      this.editing = "";
      return;
    }
    try {
      const response = await this.call("get", { name: skill.name });
      this.editText = response.content || "";
      this.editState = response.state;
      this.editing = skill.name;
    } catch (error) {
      await toastFrontendError(error?.message || "Failed to open skill", "Learned skills");
    }
  },

  async saveEdit(skill) {
    this.busy = skill.name;
    try {
      const response = await this.call("save", { name: skill.name, content: this.editText });
      await toastFrontendInfo(`${skill.name} saved (version ${response.version}).`, "Learned skills");
      this.editing = "";
      await this.load();
    } catch (error) {
      await toastFrontendError(error?.message || "Failed to save", "Learned skills");
    } finally {
      this.busy = "";
    }
  },

  async openChat(skill) {
    if (!skill.source_chat) return;
    try {
      await chatsStore.selectChat(skill.source_chat);
      closeModal();
    } catch (error) {
      await toastFrontendError("That chat no longer exists.", "Learned skills");
    }
  },
};

export const store = createStore("learnedSkillsStore", model);

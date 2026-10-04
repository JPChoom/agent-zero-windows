import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";

const SPECIFICS_PROMPT_FILE = "agent.system.main.specifics.md";

function slugify(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function emptyDraft() {
  return {
    name: "",
    title: "",
    description: "",
    context: "",
    enabled: true,
    specificsPrompt: "",
  };
}

const model = {
  profiles: [],
  loading: false,
  error: "",
  isCreating: false,
  isEditing: false,
  draft: emptyDraft(),
  originalName: "",

  init() {
    this.refresh();
  },

  async refresh() {
    this.loading = true;
    this.error = "";
    try {
      const result = await callJsonApi("subagents", { action: "list" });
      if (!result?.ok) {
        this.error = result?.error || "Failed to load agent profiles";
        this.profiles = [];
        return;
      }
      this.profiles = Array.isArray(result.data) ? result.data : [];
    } catch (error) {
      this.error = error?.message || "Failed to load agent profiles";
      this.profiles = [];
    } finally {
      this.loading = false;
    }
  },

  isUserOwned(profile) {
    return Array.isArray(profile?.origin) && profile.origin.includes("user");
  },

  originLabel(profile) {
    const origin = Array.isArray(profile?.origin) ? profile.origin : [];
    if (origin.includes("user") && origin.length === 1) return "Custom";
    if (origin.includes("user")) return "Customized";
    if (origin.includes("project")) return "Project";
    if (origin.includes("plugin")) return "Plugin";
    return "Built-in";
  },

  startCreate() {
    this.isCreating = true;
    this.isEditing = false;
    this.draft = emptyDraft();
    this.originalName = "";
  },

  async startEdit(name) {
    this.error = "";
    try {
      const result = await callJsonApi("subagents", { action: "load", name });
      if (!result?.ok) {
        globalThis.toastFrontendError?.(result?.error || "Failed to load profile", "Agent Profiles");
        return;
      }
      const data = result.data || {};
      this.draft = {
        name: data.name || name,
        title: data.title || "",
        description: data.description || "",
        context: data.context || "",
        enabled: data.enabled !== false,
        specificsPrompt: (data.prompts || {})[SPECIFICS_PROMPT_FILE] || "",
      };
      this.originalName = data.name || name;
      this.isEditing = true;
      this.isCreating = false;
    } catch (error) {
      globalThis.toastFrontendError?.(error?.message || "Failed to load profile", "Agent Profiles");
    }
  },

  cancelEdit() {
    this.isCreating = false;
    this.isEditing = false;
    this.draft = emptyDraft();
    this.originalName = "";
  },

  get slugPreview() {
    return slugify(this.draft.name);
  },

  async save() {
    const name = this.isCreating ? this.slugPreview : this.originalName;
    if (!name) {
      globalThis.toastFrontendError?.("Enter a profile name", "Agent Profiles");
      return false;
    }
    if (!this.draft.title.trim()) {
      globalThis.toastFrontendError?.("Enter a display title", "Agent Profiles");
      return false;
    }

    const prompts = {};
    if (this.draft.specificsPrompt.trim()) {
      prompts[SPECIFICS_PROMPT_FILE] = this.draft.specificsPrompt;
    }

    try {
      const result = await callJsonApi("subagents", {
        action: "save",
        name,
        data: {
          name,
          title: this.draft.title,
          description: this.draft.description,
          context: this.draft.context,
          enabled: this.draft.enabled,
          prompts,
        },
      });
      if (!result?.ok) {
        globalThis.toastFrontendError?.(result?.error || "Failed to save profile", "Agent Profiles");
        return false;
      }
      globalThis.toastFrontendSuccess?.(`Saved profile "${this.draft.title}"`, "Agent Profiles");
      this.cancelEdit();
      await this.refresh();
      return true;
    } catch (error) {
      globalThis.toastFrontendError?.(error?.message || "Failed to save profile", "Agent Profiles");
      return false;
    }
  },

  async deleteProfile(name) {
    try {
      const result = await callJsonApi("subagents", { action: "delete", name });
      if (!result?.ok) {
        globalThis.toastFrontendError?.(result?.error || "Failed to delete profile", "Agent Profiles");
        return;
      }
      globalThis.toastFrontendSuccess?.("Profile deleted", "Agent Profiles");
      if (this.originalName === name) this.cancelEdit();
      await this.refresh();
    } catch (error) {
      globalThis.toastFrontendError?.(error?.message || "Failed to delete profile", "Agent Profiles");
    }
  },
};

const store = createStore("agentProfiles", model);

export { store };

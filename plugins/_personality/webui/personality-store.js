import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";

// Plugin-local API handlers (plugins/_personality/api/*.py) are routed
// under this prefix - a bare endpoint name only resolves against the
// core api/ directory (helpers/api.py), which is not where this plugin's
// handlers live.
const API_BASE = "plugins/_personality";

export const store = createStore("personality", {
  personalities: [],
  activeId: "default",
  contextId: "",
  loading: false,
  loaded: false,

  async refresh(contextId) {
    this.contextId = contextId || "";
    this.loading = true;
    try {
      const data = await callJsonApi(`${API_BASE}/personality_list`, { context_id: this.contextId });
      if (data?.ok) {
        this.personalities = data.personalities || [];
        this.activeId = data.active || "default";
        this.loaded = true;
      }
    } catch (error) {
      console.error("personality: could not read list", error);
    } finally {
      this.loading = false;
    }
  },

  label() {
    const found = this.personalities.find((p) => p.id === this.activeId);
    return found ? found.name : "Default";
  },

  async select(id) {
    if (!this.contextId) {
      globalThis.toastFrontendError?.("Select a chat first", "Personality");
      return;
    }
    if (id === this.activeId) return;
    const previous = this.activeId;
    this.activeId = id; // optimistic
    try {
      const data = await callJsonApi(`${API_BASE}/personality_set`, {
        context_id: this.contextId,
        personality_id: id,
      });
      if (!data?.ok) {
        this.activeId = previous;
        globalThis.toastFrontendError?.(data?.error || "Could not set personality", "Personality");
        return;
      }
      globalThis.justToast?.(`Personality: ${this.label()}`, "success", 1500, "personality-select");
    } catch (error) {
      this.activeId = previous;
      globalThis.toastFrontendError?.(error?.message || "Could not set personality", "Personality");
    }
  },

  async save(id, name, prompt) {
    const data = await callJsonApi(`${API_BASE}/personality_save`, { id: id || null, name, prompt });
    if (!data?.ok) {
      globalThis.toastFrontendError?.(data?.error || "Could not save personality", "Personality");
      return null;
    }
    await this.refresh(this.contextId);
    return data.personality;
  },

  async remove(id) {
    const data = await callJsonApi(`${API_BASE}/personality_delete`, { id });
    if (!data?.ok) {
      globalThis.toastFrontendError?.(data?.error || "Could not delete personality", "Personality");
      return false;
    }
    await this.refresh(this.contextId);
    return true;
  },
});

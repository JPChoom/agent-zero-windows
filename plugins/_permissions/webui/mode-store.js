/**
 * Permission mode selector state.
 *
 * The mode lives in plugin config on the server, not in the browser: it
 * governs what the agent is allowed to do, so a value cached per-tab would
 * let two windows disagree about whether a tool needs approval.
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

export const store = createStore("permissionsMode", {
  mode: "auto",
  modes: [],
  open: false,
  loading: false,
  loaded: false,

  async refresh() {
    try {
      const data = await callJsonApi("permissions_mode", {});
      if (data?.ok) {
        this.mode = data.mode || "auto";
        this.modes = data.modes || [];
        this.loaded = true;
      }
    } catch (error) {
      // The selector keeps showing its last known value; a failed read
      // must not break the input box it sits under.
      console.error("permissions: could not read mode", error);
    }
  },

  label() {
    // Fetch on first render rather than at import time: the endpoint
    // requires auth, and this module is loaded on the login page too.
    if (!this.loaded && !this.loading) {
      this.loading = true;
      this.refresh().finally(() => (this.loading = false));
    }
    const found = this.modes.find((m) => m.id === this.mode);
    return found ? found.label : titleCase(this.mode);
  },

  async select(id) {
    this.open = false;
    if (id === this.mode) return;
    const previous = this.mode;
    this.mode = id; // optimistic, so the menu closes on a chosen value
    try {
      const data = await callJsonApi("permissions_mode", { mode: id });
      if (!data?.ok) {
        this.mode = previous; // roll back on refusal
        globalThis.toastFrontendError?.(
          data?.error || "Could not change mode",
          "Permissions"
        );
        return;
      }
      this.mode = data.mode;
      globalThis.justToast?.(
        `Permission mode: ${this.label()}`,
        "success",
        1500,
        "perm-mode"
      );
    } catch (error) {
      this.mode = previous;
      globalThis.toastFrontendError?.(
        error?.message || "Could not change mode",
        "Permissions"
      );
    }
  },
});

function titleCase(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/^\w/, (c) => c.toUpperCase());
}

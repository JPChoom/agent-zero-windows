/**
 * Permission mode selector state.
 *
 * The mode lives in plugin config on the server, not in the browser: it
 * governs what the agent is allowed to do, so a value cached per-tab would
 * let two windows disagree about whether a tool needs approval.
 */
import { callJsonApi } from "/js/api.js";

document.addEventListener("alpine:init", () => {
  Alpine.store("permissionsMode", {
    mode: "auto",
    modes: [],
    open: false,
    loading: false,

    async init() {
      await this.refresh();
    },

    async refresh() {
      try {
        const data = await callJsonApi("permissions_mode", {});
        if (data?.ok) {
          this.mode = data.mode || "auto";
          this.modes = data.modes || [];
        }
      } catch (error) {
        // The selector simply shows its last known value; a failed read
        // must not block the input box it sits under.
        console.error("permissions: could not read mode", error);
      }
    },

    label() {
      const found = this.modes.find((m) => m.id === this.mode);
      return found ? found.label : this.mode;
    },

    async select(id) {
      this.open = false;
      if (id === this.mode) return;
      const previous = this.mode;
      this.mode = id;                       // optimistic, for responsiveness
      this.loading = true;
      try {
        const data = await callJsonApi("permissions_mode", { mode: id });
        if (!data?.ok) {
          this.mode = previous;             // roll back on refusal
          window.toastFrontendError?.(data?.error || "Could not change mode", "Permissions");
          return;
        }
        this.mode = data.mode;
        window.justToast?.(`Permission mode: ${this.label()}`, "success", 1500, "perm-mode");
      } catch (error) {
        this.mode = previous;
        window.toastFrontendError?.(error?.message || "Could not change mode", "Permissions");
      } finally {
        this.loading = false;
      }
    },
  });

  Alpine.store("permissionsMode").init();
});

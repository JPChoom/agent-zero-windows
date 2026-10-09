import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";

// Settings > Check for updates on a native Windows install (api/windows_update.py).
export const store = createStore("windowsUpdate", {
  info: null,
  busy: false,
  error: "",
  done: "",
  showNotes: false,
  confirming: "",

  async refresh(force = false) {
    this.error = "";
    try {
      const data = await callJsonApi("windows_update", { action: "check", force });
      if (data?.ok) this.info = data;
    } catch (e) {
      this.error = e?.message || "Could not check for updates";
    }
  },

  get updateAvailable() {
    return Boolean(this.info?.update_available);
  },

  async _run(action, payload = {}) {
    this.busy = true;
    this.error = "";
    this.done = "";
    this.confirming = "";
    try {
      const data = await callJsonApi("windows_update", { action, ...payload });
      if (!data?.ok) {
        this.error = data?.error || "The update did not complete.";
        return;
      }
      this.done = action === "apply"
        ? `Updated to ${data.updated_to}${data.requirements_installed ? " (new packages installed)" : ""}. Restart to start using it.`
        : `Rolled back to ${data.rolled_back_to}. Restart to start using it.`;
      await this.refresh(false);
    } catch (e) {
      this.error = e?.message || "The update did not complete.";
    } finally {
      this.busy = false;
    }
  },

  apply() {
    return this._run("apply", { tag: this.info?.latest?.tag || "" });
  },

  rollback() {
    return this._run("rollback");
  },

  async restart() {
    this.busy = true;
    this.confirming = "";
    try {
      await callJsonApi("windows_update", { action: "restart" });
      this.done = "Restarting... this page reconnects when Agent Zero is back.";
    } catch (e) {
      this.error = e?.message || "Could not restart";
    } finally {
      this.busy = false;
    }
  },
});

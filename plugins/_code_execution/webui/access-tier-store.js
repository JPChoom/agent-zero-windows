import { createStore } from "/js/AlpineStore.js";
import { store as folderPickerStore } from "/components/modals/folder-picker/folder-picker-store.js";

// Backs the "Browse..." button next to Allowed external roots on this
// plugin's config page: opens the folder picker and appends the chosen
// absolute path as a new line, deduplicated.
const model = {
  browseForExternalRoot(config) {
    folderPickerStore.open("", (path) => {
      if (!path) return;
      const lines = String(config.allowed_external_roots || "")
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);
      if (!lines.includes(path)) lines.push(path);
      config.allowed_external_roots = lines.join("\n");
    });
  },
};

export const store = createStore("codeExecutionAccessTier", model);

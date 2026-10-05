import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import { justToast } from "/index.js";

// "Recently deleted" chats (api/chat_trash.py over helpers/chat_trash.py).
// Deleted chats stay restorable for retentionDays, then are purged.
const model = {
  items: [],
  retentionDays: 30,
  loading: false,
  error: "",
  busy: {},

  // The modal refreshes the list itself on open (x-init).
  async open() {
    await globalThis.openModal("modals/chat-trash/chat-trash.html");
  },

  async refresh() {
    this.loading = true;
    this.error = "";
    try {
      const result = await callJsonApi("/chat_trash", { action: "list" });
      this.items = Array.isArray(result?.items) ? result.items : [];
      this.retentionDays = Number(result?.retention_days) || 30;
    } catch (e) {
      this.error = e?.message || "Could not load deleted chats.";
    } finally {
      this.loading = false;
    }
  },

  // Restore a trashed chat and open it. Returns the restored context id.
  async restore(trashId, { select = true } = {}) {
    if (!trashId || this.busy[trashId]) return null;
    this.busy = { ...this.busy, [trashId]: true };
    try {
      const result = await callJsonApi("/chat_trash", { action: "restore", trash_id: trashId });
      this.items = this.items.filter((item) => item.trash_id !== trashId);
      const chats = globalThis.Alpine?.store("chats");
      if (chats?._removing) {
        // An undo can land before the delete's sync settled; let the chat
        // list show it again.
        const { [result?.context_id]: _gone, ...rest } = chats._removing;
        chats._removing = rest;
      }
      if (select && result?.context_id) chats?.selectChat(result.context_id);
      justToast("Chat restored", "success", 1500, "chat-trash");
      return result?.context_id || null;
    } catch (e) {
      globalThis.toastFrontendError?.(e?.message || "Could not restore chat", "Recently deleted");
      return null;
    } finally {
      const { [trashId]: _done, ...rest } = this.busy;
      this.busy = rest;
    }
  },

  async deleteForever(trashId) {
    if (!trashId || this.busy[trashId]) return;
    this.busy = { ...this.busy, [trashId]: true };
    try {
      await callJsonApi("/chat_trash", { action: "delete", trash_id: trashId });
      this.items = this.items.filter((item) => item.trash_id !== trashId);
    } catch (e) {
      globalThis.toastFrontendError?.(e?.message || "Could not delete chat", "Recently deleted");
    } finally {
      const { [trashId]: _done, ...rest } = this.busy;
      this.busy = rest;
    }
  },

  async emptyTrash() {
    try {
      await callJsonApi("/chat_trash", { action: "empty" });
      this.items = [];
    } catch (e) {
      globalThis.toastFrontendError?.(e?.message || "Could not empty the trash", "Recently deleted");
    }
  },

  displayName(item) {
    return item?.name || "Untitled chat";
  },

  formatDate(iso) {
    const date = iso ? new Date(iso) : null;
    if (!date || Number.isNaN(date.getTime())) return "";
    return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  },

  daysLeft(item) {
    const expires = item?.expires_at ? new Date(item.expires_at) : null;
    if (!expires || Number.isNaN(expires.getTime())) return "";
    const days = Math.max(0, Math.ceil((expires - Date.now()) / 86_400_000));
    return days <= 1 ? "Deleted forever within a day" : `Deleted forever in ${days} days`;
  },
};

export const store = createStore("chatTrash", model);

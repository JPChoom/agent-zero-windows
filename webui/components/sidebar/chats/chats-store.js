import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import {
  sendJsonData,
  getContext,
  setContext,
  toastFetchError,
  toast,
  justToast,
  getConnectionStatus,
} from "/index.js";
import { store as notificationStore } from "/components/notifications/notification-store.js";
import { store as tasksStore } from "/components/sidebar/tasks/tasks-store.js";
import { store as syncStore } from "/components/sync/sync-store.js";
import { store as chatTrashStore } from "/components/modals/chat-trash/chat-trash-store.js";
import { store as chatInputStore } from "/components/chat/input/input-store.js";

const model = {
  contexts: [],
  selected: "",
  selectedContext: null,
  loggedIn: false,
  expandedParents: {},
  // Chats being deleted: id -> "pending" (server call in flight) or "done"
  // (server confirmed, waiting for a state sync without it). Kept out of
  // the list so a sync snapshot taken before the delete cannot bring the
  // row back.
  _removing: {},

  // for convenience
  getSelectedChatId() {
    return this.selected;
  },

  getSelectedContext(){
    return this.selectedContext;
  },

  init() {
    this.loggedIn = Boolean(window.runtimeInfo && window.runtimeInfo.loggedIn);

    // URL parameter takes priority (e.g. ?ctxid=abc from "open in new window")
    const urlParams = new URL(window.location.href).searchParams;
    const urlCtxId = urlParams.get("ctxid");
    if (urlCtxId) {
      const cleanUrl = new URL(window.location.href);
      cleanUrl.searchParams.delete("ctxid");
      window.history.replaceState({}, "", cleanUrl);
      this.selectChat(urlCtxId);
      return;
    }

    // Initialize from sessionStorage
    const lastSelectedChat = sessionStorage.getItem("lastSelectedChat");
    if (lastSelectedChat) {
      this.selectChat(lastSelectedChat);
    }
  },

  // Update contexts from polling
  applyContexts(contextsList) {
    let list = contextsList;
    const removingIds = Object.keys(this._removing);
    if (removingIds.length) {
      const incoming = new Set(contextsList.map((ctx) => ctx.id));
      const removing = { ...this._removing };
      for (const id of removingIds) {
        if (removing[id] === "done" && !incoming.has(id)) delete removing[id];
      }
      this._removing = removing;
      list = contextsList.filter((ctx) => !removing[ctx.id]);
    }
    // Sort by created_at time (newer first)
    this.contexts = [...list].sort(
      (a, b) => (b.created_at || 0) - (a.created_at || 0)
    );

    // Keep selectedContext in sync when the currently selected context's
    // metadata changes (e.g. project activation/deactivation).
    if (this.selected) {
      const selectedId = this.selected;
      const updated = this.contexts.find((ctx) => ctx.id === selectedId);
      if (updated) {
        this.selectedContext = updated;
        const nextExpandedParents = { ...this.expandedParents };
        if (updated.parent_context_id) {
          nextExpandedParents[updated.parent_context_id] = true;
        } else if (
          this.hasChildren(selectedId) &&
          nextExpandedParents[selectedId] === undefined
        ) {
          nextExpandedParents[selectedId] = true;
        }
        this.expandedParents = nextExpandedParents;
      }
    }
  },

  topLevelContexts() {
    return this.contexts.filter((ctx) => !ctx?.parent_context_id);
  },

  childContexts(parentId) {
    return this.contexts.filter((ctx) => ctx?.parent_context_id === parentId);
  },

  hasChildren(parentId) {
    return this.childContexts(parentId).length > 0;
  },

  isExpanded(parentId) {
    return Boolean(this.expandedParents?.[parentId]);
  },

  toggleChildren(parentId) {
    if (!parentId || !this.hasChildren(parentId)) return;
    this.expandedParents = {
      ...this.expandedParents,
      [parentId]: !this.expandedParents?.[parentId],
    };
  },

  displayName(context) {
    if (!context) return "";
    return context.parent_context_label || context.name || `Chat #${context.no}`;
  },

  // Select a chat
  async selectChat(id) {
    const currentContext = getContext();
    if (id === currentContext) return; // already selected

    // Proceed with context selection
    setContext(id);

    // Update selection state (will also persist to localStorage)
    this.setSelected(id);

    // In push mode, context switching triggers a new `state_request` via setContext().
    // Keep polling only as a degraded-mode fallback.
    try {
      const mode = typeof syncStore.mode === "string" ? syncStore.mode : null;
      const shouldFallbackPoll = mode === "DEGRADED";
      if (shouldFallbackPoll && typeof globalThis.poll === "function") {
        globalThis.poll();
      }
    } catch (_e) {
      // no-op
    }
  },

  // Delete a chat
  async killChat(id) {
    if (!id) {
      console.error("No chat ID provided for deletion");
      return;
    }

    if (this._removing[id]) return;

    // Optimistic: the row disappears on the confirming click. Removing a
    // long chat (folder delete, scheduler reload) and switching away from
    // it used to block the UI for seconds, which read as a missed click.
    const removed = this.contexts.find((ctx) => ctx.id === id);
    this._removing = { ...this._removing, [id]: "pending" };
    this.contexts = this.contexts.filter((ctx) => ctx.id !== id);
    if (this.selected === id) {
      this.switchFromContext(id).catch((e) => console.error("Error switching chat:", e));
    }

    try {
      const result = await sendJsonData("/chat_remove", { context: id });
      this._removing = { ...this._removing, [id]: "done" };
      // Saved chats go to the trash (api/chat_trash.py) and can be undone;
      // a never-saved empty chat has nothing to restore.
      const trashId = result?.trash_id;
      if (trashId) {
        justToast("Chat moved to Recently deleted", "success", 6000, "chat-removal", {
          label: "Undo",
          run: () => chatTrashStore.restore(trashId),
        });
      } else {
        justToast("Chat deleted", "success", 1000, "chat-removal");
      }
    } catch (e) {
      console.error("Error deleting chat:", e);
      const { [id]: _dropped, ...rest } = this._removing;
      this._removing = rest;
      if (removed && !this.contexts.some((ctx) => ctx.id === id)) {
        this.contexts = [...this.contexts, removed].sort(
          (a, b) => (b.created_at || 0) - (a.created_at || 0)
        );
      }
      toastFetchError("Error deleting chat", e);
    }
  },

  async renameChat(id) {
    if (!id) return;
    const current = this.contexts.find((ctx) => ctx.id === id);
    const proposed = globalThis.prompt(
      "Rename chat",
      current ? this.displayName(current) : ""
    );
    // null means cancelled; an empty string is a mistake rather than an
    // instruction to clear the name, so both leave the chat untouched.
    if (proposed === null || !proposed.trim()) return;

    try {
      const response = await sendJsonData("/chat_rename", {
        context: id,
        name: proposed,
      });
      if (response && response.ok === false) {
        justToast(response.error || "Could not rename chat", "error", 3000);
        return;
      }
      // Reflect the server's version: it collapses whitespace and truncates,
      // so echoing the raw input would briefly show a name that is not what
      // was stored.
      const stored = (response && response.name) || proposed.trim();
      this.contexts = this.contexts.map((ctx) =>
        ctx.id === id ? { ...ctx, name: stored } : ctx
      );
      justToast("Chat renamed", "success", 1000, "chat-rename");
    } catch (e) {
      console.error("Error renaming chat:", e);
      toastFetchError("Error renaming chat", e);
    }
  },

  // Switch from a context that's being deleted
  async switchFromContext(id) {
    // Find an alternate chat to switch to
    let alternateChat = null;
    for (let i = 0; i < this.contexts.length; i++) {
      if (this.contexts[i].id !== id) {
        alternateChat = this.contexts[i];
        break;
      }
    }

    if (alternateChat) {
      await this.selectChat(alternateChat.id);
    } else {
      // If no other chats, create a new empty context
      this.deselectChat();
      //await this.newChat();
    }
  },

  // Reset current chat
  async resetChat(ctxid = null) {
    try {
      const context = ctxid || this.selected || getContext();
      await sendJsonData("/chat_reset", {
        context
      });

      // Increment reset counter
      if (typeof globalThis.resetCounter === 'number') {
        globalThis.resetCounter = globalThis.resetCounter + 1;
      }      
    } catch (e) {
      toastFetchError("Error resetting chat", e);
    }
  },

  // Create new chat
  async newChat() {
    try {

      // first create a new chat on the backend
      const response = await sendJsonData("/chat_create", {
        current_context: this.selected
      });

      if (response.ok) {
        await this.selectChat(response.ctxid);
        document.dispatchEvent(new CustomEvent("chat-created", { detail: { ctxid: response.ctxid } }));
        return response.ctxid;
      }

    } catch (e) {
      toastFetchError("Error creating new chat", e);
    }
    return null;
  },

  deselectChat(){
    globalThis.deselectChat(); //TODO move here
  },

  // Smoothly scroll the chats list to top if present
  _scrollChatsToTop() {
    const listEl = document.querySelector('#chats-section .chats-config-list');
    if (!listEl) return; // no-op if not in DOM
    listEl.scrollTo({ top: 0, behavior: 'smooth' });
  },

  // Load chats from files
  async loadChats() {
    try {
      const fileContents = await this.readJsonFiles();
      const response = await sendJsonData("/chat_load", { chats: fileContents });

      if (!response) {
        toast("No response returned.", "error");
      } else {
        // Set context to first loaded chat
        if (response.ctxids?.[0]) {
          setContext(response.ctxids[0]);
        }
        toast("Chats loaded.", "success");
      }
    } catch (e) {
      toastFetchError("Error loading chats", e);
    }
  },

  // Save current chat
  async saveChat() {
    try {
      const context = this.selected || getContext();
      const response = await sendJsonData("/chat_export", { ctxid: context });

      if (!response) {
        toast("No response returned.", "error");
      } else {
        this.downloadFile(response.ctxid + ".json", response.content);
        toast("Chat file downloaded.", "success");
      }
    } catch (e) {
      toastFetchError("Error saving chat", e);
    }
  },

  // Helper: read JSON files
  readJsonFiles() {
    return new Promise((resolve, reject) => {
      const input = document.createElement("input");
      input.type = "file";
      input.accept = ".json";
      input.multiple = true;

      input.click();

      input.onchange = async () => {
        const files = input.files;
        if (!files.length) {
          resolve([]);
          return;
        }

        const filePromises = Array.from(files).map((file) => {
          return new Promise((fileResolve, fileReject) => {
            const reader = new FileReader();
            reader.onload = () => fileResolve(reader.result);
            reader.onerror = fileReject;
            reader.readAsText(file);
          });
        });

        try {
          const fileContents = await Promise.all(filePromises);
          resolve(fileContents);
        } catch (error) {
          reject(error);
        }
      };
    });
  },

  // Helper: download file
  downloadFile(filename, content) {
    const blob = new Blob([content], { type: "application/json" });
    const link = document.createElement("a");
    const url = URL.createObjectURL(blob);
    link.href = url;
    link.download = filename;
    link.click();

    setTimeout(() => {
      URL.revokeObjectURL(url);
    }, 0);
  },

  // Check if context exists
  contains(contextId) {
    return this.contexts.some((ctx) => ctx.id === contextId);
  },

  // Get first context ID
  firstId() {
    return this.contexts.length > 0 ? this.contexts[0].id : null;
  },

  // Set selected context
  setSelected(contextId) {
    this.selected = contextId || "";
    this.selectedContext = this.contexts.find((ctx) => ctx.id === this.selected);
    // if not found in contexts, try to find in tasks < not nice, will need refactor later
    if(!this.selectedContext) this.selectedContext = tasksStore.tasks.find((ctx) => ctx.id === this.selected);
    if (this.selected) {
      sessionStorage.setItem("lastSelectedChat", this.selected);
    } else {
      sessionStorage.removeItem("lastSelectedChat");
    }
  },

  // Restart the backend
  async restart() {
    // Check connection status (avoid spamming requests when already disconnected)
    const connectionStatus = getConnectionStatus();
    if (connectionStatus === false) {
      await notificationStore.frontendError(
        "Backend disconnected, cannot restart.",
        "Restart Error",
      );
      return;
    }

    // Create a backend notification first so other tabs have a chance to show it
    // before the process is replaced.
    const notificationId = await notificationStore.info(
      "Restarting...",
      "System Restart",
      "",
      9999,
      "restart",
    );

    // Best-effort: wait briefly for the notification to arrive via state sync so
    // the initiating tab (and typically other tabs) renders the toast before restart.
    if (notificationId) {
      const deadline = Date.now() + 800;
      while (Date.now() < deadline) {
        try {
          
          const stack = Array.isArray(notificationStore.toastStack) ? notificationStore.toastStack : null;
          if (stack && stack.some((toast) => toast && toast.id === notificationId)) {
            break;
          }
        } catch (_err) {
          break;
        }
        await new Promise((resolve) => setTimeout(resolve, 25));
      }
    }

    // The restart endpoint usually drops the connection as the process is replaced.
    // Do not wait on /health - recovery is driven by WebSocket CSRF preflight + reconnect.
    try {
      await sendJsonData("/restart", {});
    } catch (_e) {
      // ignore
    }
  },

  async logout() {
    try {
      await callJsonApi("/logout", {});
    } catch (_e) {
      // ignore
    }

    try {
      sessionStorage.removeItem("lastSelectedChat");
      sessionStorage.removeItem("lastSelectedTask");
    } catch (_e) {
      // ignore
    }

    try {
      window.location.reload();
    } catch (_e) {
      // ignore
    }
  }
};

const store = createStore("chats", model);

export { store };

import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import { openModal, closeModal } from "/js/modals.js";

export const POPUP_PATH = "/plugins/_safety_policy/webui/approval-popup.html";

// Ids already offered as a popup this page session. Kept outside the store
// so Alpine never wraps it in a reactive proxy. A popup the user dismissed
// without deciding is not re-offered; the in-chat buttons remain.
const offered = new Set();

const model = {
  request: null, // { approvalId, category, command, host, content, expiresAt }
  queue: [],
  busy: false,
  now: Date.now() / 1000,
  _timer: null,

  get remainingSeconds() {
    if (!this.request?.expiresAt) return null;
    return Math.max(0, Math.round(this.request.expiresAt - this.now));
  },

  // Called by the chat message handler for every unresolved approval it
  // renders. Renders repeat, so this must be idempotent per id.
  offer(request) {
    if (!request?.approvalId || offered.has(request.approvalId)) return;
    if (request.expiresAt && request.expiresAt <= Date.now() / 1000) return;
    offered.add(request.approvalId);
    this.queue.push(request);
    if (!this.request) this._showNext();
  },

  // Called when a decision lands from anywhere (popup, chat buttons,
  // timeout), so a popup never lingers over an already-settled request.
  onResolved(approvalId) {
    offered.add(approvalId);
    this.queue = this.queue.filter((r) => r.approvalId !== approvalId);
    if (this.request?.approvalId === approvalId) closeModal(POPUP_PATH);
  },

  async respond(approved, remember = false) {
    const request = this.request;
    if (!request || this.busy) return;
    this.busy = true;
    try {
      const result = await callJsonApi("safety_policy_approve", {
        approval_id: request.approvalId,
        approved,
        remember,
      });
      // A host that failed to save must be surfaced: the user would
      // otherwise believe they had stopped being asked when they had not.
      if (result?.error) window.toastFrontendError?.(result.error, "Safety Policy");
      else if (result?.remembered) window.toastFrontendSuccess?.(`${result.remembered} added to allowed download hosts`, "Safety Policy");
      else if (result && !result.resolved) window.toastFrontendWarning?.("This request had already ended", "Safety Policy");
      this.onResolved(request.approvalId);
    } catch (error) {
      window.toastFrontendError?.(error?.message || "Failed to submit decision", "Safety Policy");
    } finally {
      this.busy = false;
    }
  },

  _showNext() {
    const now = Date.now() / 1000;
    this.queue = this.queue.filter((r) => !r.expiresAt || r.expiresAt > now);
    const next = this.queue.shift();
    if (!next) return;
    this.request = next;
    this.now = now;
    this._startTimer();
    // openModal resolves when the modal is removed, however that happened
    // (a decision, Escape, the close button), so cleanup lives here once.
    openModal(POPUP_PATH).then(() => {
      this._stopTimer();
      this.request = null;
      requestAnimationFrame(() => this._showNext());
    });
  },

  _startTimer() {
    this._stopTimer();
    this._timer = setInterval(() => {
      this.now = Date.now() / 1000;
      if (this.remainingSeconds === 0 && this.request) closeModal(POPUP_PATH);
    }, 1000);
  },

  _stopTimer() {
    if (this._timer) clearInterval(this._timer);
    this._timer = null;
  },
};

export const store = createStore("safetyApprovalPopup", model);

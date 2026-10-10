import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import { createBackoff } from "/js/backoff.js";

const POLL_INTERVAL_MS = 5000;
// Polling slows down while requests fail (see /js/backoff.js).
const pollBackoff = createBackoff({ baseMs: POLL_INTERVAL_MS });

function formatTokens(value) {
  const number = Number(value) || 0;
  if (number >= 1000) return `${(number / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return String(number);
}

const model = {
  tokens: 0,
  maxTokens: 0,
  percent: null,
  available: false,
  _pollTimer: null,

  onMount() {
    this.refresh();
    this.startPolling();
  },

  cleanup() {
    this.stopPolling();
  },

  startPolling() {
    if (this._pollTimer) return;
    this._pollTimer = globalThis.setInterval(() => this.refresh(), POLL_INTERVAL_MS);
  },

  stopPolling() {
    if (!this._pollTimer) return;
    globalThis.clearInterval(this._pollTimer);
    this._pollTimer = null;
  },

  async refresh() {
    const contextId = globalThis.getContext?.();
    if (!contextId) {
      this.available = false;
      return;
    }
    if (!pollBackoff.ready()) return;
    try {
      const result = await callJsonApi("plugins/_context_usage/context_usage_get", { context: contextId });
      pollBackoff.succeed();
      if (!result?.ok) {
        this.available = false;
        return;
      }
      this.tokens = result.tokens || 0;
      this.maxTokens = result.max_tokens || 0;
      this.percent = result.percent;
      this.available = this.maxTokens > 0;
    } catch {
      pollBackoff.fail();
      this.available = false;
    }
  },

  get label() {
    if (!this.available) return "";
    return this.maxTokens
      ? `${formatTokens(this.tokens)} / ${formatTokens(this.maxTokens)}`
      : formatTokens(this.tokens);
  },

  get percentLabel() {
    return this.percent === null || this.percent === undefined ? "" : `${Math.round(this.percent)}%`;
  },

  get severity() {
    if (this.percent === null || this.percent === undefined) return "normal";
    if (this.percent >= 90) return "critical";
    if (this.percent >= 70) return "warning";
    return "normal";
  },

  async openDetail() {
    const { store: contextStore } = await import("/components/modals/context/context-store.js");
    contextStore.open?.();
  },
};

const store = createStore("contextUsage", model);

export { store };

import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";

const POLL_MS = 1000;
const IDLE_POLL_MS = 2000;
const FAILED_POLL_MS = 10000;

const PHASES = {
  reading: "reading prompt...",
  thinking: "thinking",
  writing: "writing",
};

function sectionOpen() {
  return globalThis.Alpine?.store("sidebar")?.isSectionOpen("info") ?? true;
}

const model = {
  expanded: false,
  phase: "idle",
  rate: null,
  detail: {},
  last: null,
  _mounted: 0,
  _timer: null,

  get active() {
    return this.phase !== "idle";
  },

  get label() {
    const rate = this.active ? this.rate : this.last?.tok_s;
    if (this.phase === "reading") return PHASES.reading;
    return rate === null || rate === undefined ? "-- tok/s" : `${Math.round(rate)} tok/s`;
  },

  get phaseLabel() {
    return PHASES[this.phase] || "";
  },

  get rows() {
    const source = this.active ? this.detail : this.last || {};
    const rows = [];
    if (source.model) rows.push(["Model", source.role === "subordinate" ? `${source.model} (subordinate)` : source.model]);
    if (source.first_token_s !== null && source.first_token_s !== undefined) {
      rows.push(["First token", `${source.first_token_s.toFixed(1)} s`]);
    }
    if (source.prompt_kept !== null && source.prompt_kept !== undefined) {
      rows.push(["Prompt unchanged", `${Math.round(source.prompt_kept * 100)}%`]);
    }
    if (source.prompt_tokens) rows.push(["Prompt", `~${Math.round(source.prompt_tokens / 100) / 10}k tokens`]);
    return rows;
  },

  onMount() {
    this._mounted += 1;
    this._schedule(0);
  },

  cleanup() {
    this._mounted = Math.max(0, this._mounted - 1);
    if (!this._mounted) this._stop();
  },

  _stop() {
    clearTimeout(this._timer);
    this._timer = null;
  },

  _schedule(delay) {
    this._stop();
    if (this._mounted) this._timer = setTimeout(() => this._poll(), delay);
  },

  async _poll() {
    if (document.hidden || !sectionOpen()) {
      this._schedule(IDLE_POLL_MS);
      return;
    }
    try {
      const state = await callJsonApi("/plugins/_perf/live", {});
      this.phase = state.phase || "idle";
      this.rate = state.tok_s ?? null;
      this.detail = state;
      this.last = state.last || null;
      this._schedule(this.active ? POLL_MS : IDLE_POLL_MS);
    } catch {
      this.phase = "idle";
      this._schedule(FAILED_POLL_MS);
    }
  },
};

export const store = createStore("speedCounter", model);

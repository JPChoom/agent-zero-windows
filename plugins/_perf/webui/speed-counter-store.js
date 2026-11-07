import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";

const POLL_MS = 1000;
const PAUSED_POLL_MS = 2000;
const FAILED_POLL_MS = 10000;

// The graph: like Task Manager, the last 60 seconds with the newest on the right.
const GRAPH_SECONDS = 60;
const GRAPH_GAP_SECONDS = 5; // no reading this long reads as zero, not a slope
const GRAPH_WIDTH = 120;
const GRAPH_HEIGHT = 40;
const GRAPH_SCALE_STEP = 50; // tok/s; the top of the graph rounds up to this

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
  history: [], // [time in seconds, tok/s]
  now: 0,
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

  get graphTop() {
    const peak = Math.max(0, ...this.history.map((point) => point[1]));
    return Math.max(1, Math.ceil(peak / GRAPH_SCALE_STEP)) * GRAPH_SCALE_STEP;
  },

  get graphLine() {
    const top = this.graphTop;
    return this.history
      .map(([time, rate]) => {
        const x = GRAPH_WIDTH * (1 - (this.now - time) / GRAPH_SECONDS);
        const y = GRAPH_HEIGHT * (1 - Math.min(rate, top) / top);
        return `${x.toFixed(2)},${y.toFixed(2)}`;
      })
      .join(" ");
  },

  get graphArea() {
    if (!this.history.length) return "";
    const start = GRAPH_WIDTH * (1 - (this.now - this.history[0][0]) / GRAPH_SECONDS);
    return `${start.toFixed(2)},${GRAPH_HEIGHT} ${this.graphLine} ${GRAPH_WIDTH},${GRAPH_HEIGHT}`;
  },

  _addReading(rate, now = Date.now() / 1000) {
    const newest = this.history[this.history.length - 1];
    const gap = newest && now - newest[0] > GRAPH_GAP_SECONDS ? [[newest[0], 0], [now, 0]] : [];
    this.history = [...this.history, ...gap, [now, rate]].filter((point) => now - point[0] <= GRAPH_SECONDS);
    this.now = now;
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
      this._schedule(PAUSED_POLL_MS);
      return;
    }
    try {
      const state = await callJsonApi("/plugins/_perf/live", {});
      this.phase = state.phase || "idle";
      this.rate = state.tok_s ?? null;
      this.detail = state;
      this.last = state.last || null;
      this._addReading(this.active ? this.rate || 0 : 0);
      this._schedule(POLL_MS);
    } catch {
      this.phase = "idle";
      this._schedule(FAILED_POLL_MS);
    }
  },
};

export const store = createStore("speedCounter", model);

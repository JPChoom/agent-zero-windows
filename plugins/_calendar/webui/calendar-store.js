import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import { toUserWallClockISOString } from "/js/time-utils.js";

const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const WEEKDAY_LABELS_LONG = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTH_LABELS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const GRID_COLUMNS = 7;
const MONTH_GRID_ROWS = 6;
const VIEW_MODES = ["month", "week", "day"];
const VIEW_MODE_STORAGE_KEY = "a0.calendar.viewMode";
const HOUR_ROW_HEIGHT = 48;
const DEFAULT_CREATE_HOUR = 9;
// Tasks fire at a point in time with no real duration, so overlap is a
// visual concept: two events within this many minutes of each other are
// treated as concurrent and placed side by side instead of stacked on top
// of each other.
const OVERLAP_WINDOW_MINUTES = 30;

function dateKey(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function startOfMonth(date) {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

function addDays(date, amount) {
  const next = new Date(date);
  next.setDate(next.getDate() + amount);
  return next;
}

function isSameDate(left, right) {
  return left.getFullYear() === right.getFullYear()
    && left.getMonth() === right.getMonth()
    && left.getDate() === right.getDate();
}

function startOfWeek(date) {
  return addDays(new Date(date.getFullYear(), date.getMonth(), date.getDate()), -date.getDay());
}

function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function eventVisualInterval(event) {
  const start = event.localDate.getTime();
  return [start, start + OVERLAP_WINDOW_MINUTES * 60000];
}

// Groups events into overlapping clusters, then greedily assigns each
// event a column within its cluster (classic day-view calendar layout:
// place in the first column whose last event has already ended, else open
// a new column). Every event in a cluster gets the cluster's total column
// count so they can be rendered at equal width, side by side.
function layoutDayEvents(events) {
  if (!events.length) return [];
  const sorted = [...events].sort((left, right) => left.localDate - right.localDate);

  const clusters = [];
  let currentCluster = [];
  let clusterEnd = -Infinity;
  for (const event of sorted) {
    const [start, end] = eventVisualInterval(event);
    if (currentCluster.length && start >= clusterEnd) {
      clusters.push(currentCluster);
      currentCluster = [];
      clusterEnd = -Infinity;
    }
    currentCluster.push(event);
    clusterEnd = Math.max(clusterEnd, end);
  }
  if (currentCluster.length) clusters.push(currentCluster);

  const positioned = [];
  for (const cluster of clusters) {
    const columnEnds = [];
    const columnByEvent = new Map();
    for (const event of cluster) {
      const [start, end] = eventVisualInterval(event);
      let column = columnEnds.findIndex((columnEnd) => start >= columnEnd);
      if (column === -1) {
        column = columnEnds.length;
        columnEnds.push(end);
      } else {
        columnEnds[column] = end;
      }
      columnByEvent.set(event, column);
    }
    const columnCount = columnEnds.length;
    for (const event of cluster) {
      positioned.push({ ...event, columnIndex: columnByEvent.get(event), columnCount });
    }
  }
  return positioned;
}

function readStoredViewMode() {
  try {
    const stored = window.localStorage?.getItem(VIEW_MODE_STORAGE_KEY);
    return VIEW_MODES.includes(stored) ? stored : "month";
  } catch {
    return "month";
  }
}

const model = {
  viewDate: new Date(),
  viewMode: readStoredViewMode(),
  events: [],
  eventsByDate: {},
  loading: false,
  error: "",
  weekdayLabels: WEEKDAY_LABELS,
  hourRows: Array.from({ length: 24 }, (_, hour) => hour),

  init() {},

  async onOpen() {
    await this.fetchEvents();
  },

  get isTimeGridView() {
    return this.viewMode === "week" || this.viewMode === "day";
  },

  get gridSpanDays() {
    if (this.viewMode === "day") return 1;
    if (this.viewMode === "week") return GRID_COLUMNS;
    return MONTH_GRID_ROWS * GRID_COLUMNS;
  },

  get periodLabel() {
    if (this.viewMode === "day") {
      const day = startOfDay(this.viewDate);
      return `${WEEKDAY_LABELS_LONG[day.getDay()]}, ${MONTH_LABELS[day.getMonth()]} ${day.getDate()}, ${day.getFullYear()}`;
    }
    if (this.viewMode === "week") {
      const weekStart = startOfWeek(this.viewDate);
      const weekEnd = addDays(weekStart, 6);
      const startLabel = `${MONTH_LABELS[weekStart.getMonth()].slice(0, 3)} ${weekStart.getDate()}`;
      const endLabel = weekStart.getMonth() === weekEnd.getMonth()
        ? `${weekEnd.getDate()}`
        : `${MONTH_LABELS[weekEnd.getMonth()].slice(0, 3)} ${weekEnd.getDate()}`;
      return `${startLabel} – ${endLabel}, ${weekEnd.getFullYear()}`;
    }
    return `${MONTH_LABELS[this.viewDate.getMonth()]} ${this.viewDate.getFullYear()}`;
  },

  get gridStart() {
    if (this.viewMode === "day") {
      return startOfDay(this.viewDate);
    }
    if (this.viewMode === "week") {
      return startOfWeek(this.viewDate);
    }
    const firstOfMonth = startOfMonth(this.viewDate);
    return addDays(firstOfMonth, -firstOfMonth.getDay());
  },

  get calendarWeeks() {
    const today = new Date();
    const weeks = [];
    let cursor = this.gridStart;
    for (let week = 0; week < MONTH_GRID_ROWS; week++) {
      const days = [];
      for (let column = 0; column < GRID_COLUMNS; column++) {
        const key = dateKey(cursor);
        days.push({
          date: cursor,
          dateKey: key,
          dayNumber: cursor.getDate(),
          isCurrentMonth: cursor.getMonth() === this.viewDate.getMonth(),
          isToday: isSameDate(cursor, today),
          events: this.eventsByDate[key] || [],
        });
        cursor = addDays(cursor, 1);
      }
      weeks.push(days);
    }
    return weeks;
  },

  get timeGridDays() {
    const today = new Date();
    const columnCount = this.viewMode === "day" ? 1 : GRID_COLUMNS;
    const days = [];
    let cursor = this.gridStart;
    for (let column = 0; column < columnCount; column++) {
      const key = dateKey(cursor);
      days.push({
        date: cursor,
        dateKey: key,
        dayNumber: cursor.getDate(),
        weekdayLabel: WEEKDAY_LABELS[cursor.getDay()],
        isToday: isSameDate(cursor, today),
        events: layoutDayEvents(this.eventsByDate[key] || []),
      });
      cursor = addDays(cursor, 1);
    }
    return days;
  },

  get hourRowHeight() {
    return HOUR_ROW_HEIGHT;
  },

  // The gutter and each day column must be given this as an explicit
  // height. Left to flexbox cross-axis stretch, Chromium sizes them to
  // the scroll container's visible height and then fails to paint the
  // hairline row borders for content past that box, even though the rows
  // themselves stay laid out and scrollable correctly.
  get totalGridHeight() {
    return this.hourRows.length * HOUR_ROW_HEIGHT;
  },

  get nowIndicatorTop() {
    const now = new Date();
    return ((now.getHours() * 60 + now.getMinutes()) / 60) * HOUR_ROW_HEIGHT;
  },

  isTodayColumn(day) {
    return Boolean(day?.isToday);
  },

  hourLabel(hour) {
    const period = hour < 12 ? "AM" : "PM";
    const displayHour = hour % 12 === 0 ? 12 : hour % 12;
    return `${displayHour} ${period}`;
  },

  eventTopPx(event) {
    const eventDate = event?.localDate || new Date(event?.start);
    if (Number.isNaN(eventDate.getTime())) return 0;
    return ((eventDate.getHours() * 60 + eventDate.getMinutes()) / 60) * HOUR_ROW_HEIGHT;
  },

  eventColumnStyle(event) {
    const columnCount = event?.columnCount || 1;
    const columnIndex = event?.columnIndex || 0;
    const gap = 2;
    const widthPercent = 100 / columnCount;
    const leftPercent = widthPercent * columnIndex;
    return `left: calc(${leftPercent}% + ${gap}px); width: calc(${widthPercent}% - ${gap * 2}px);`;
  },

  async setViewMode(mode) {
    const nextMode = VIEW_MODES.includes(mode) ? mode : "month";
    if (nextMode === this.viewMode) return;
    this.viewMode = nextMode;
    try {
      window.localStorage?.setItem(VIEW_MODE_STORAGE_KEY, nextMode);
    } catch {
      /* ignore storage failures */
    }
    await this.fetchEvents();
  },

  async selectDay(selectedDateKey) {
    if (!selectedDateKey) return;
    const [year, month, day] = selectedDateKey.split("-").map(Number);
    if (!year || !month || !day) return;
    this.viewDate = new Date(year, month - 1, day);
    await this.setViewMode("day");
  },

  async prevPeriod() {
    if (this.viewMode === "day") {
      this.viewDate = addDays(this.viewDate, -1);
    } else if (this.viewMode === "week") {
      this.viewDate = addDays(this.viewDate, -7);
    } else {
      this.viewDate = new Date(this.viewDate.getFullYear(), this.viewDate.getMonth() - 1, 1);
    }
    await this.fetchEvents();
  },

  async nextPeriod() {
    if (this.viewMode === "day") {
      this.viewDate = addDays(this.viewDate, 1);
    } else if (this.viewMode === "week") {
      this.viewDate = addDays(this.viewDate, 7);
    } else {
      this.viewDate = new Date(this.viewDate.getFullYear(), this.viewDate.getMonth() + 1, 1);
    }
    await this.fetchEvents();
  },

  async goToday() {
    this.viewDate = new Date();
    await this.fetchEvents();
  },

  async fetchEvents() {
    this.loading = true;
    this.error = "";
    try {
      const start = this.gridStart;
      const end = addDays(start, this.gridSpanDays);
      const result = await callJsonApi("plugins/_calendar/calendar_events", {
        start: start.toISOString(),
        end: end.toISOString(),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      });
      if (!result?.ok) {
        this.error = result?.error || "Failed to load calendar events";
        this.events = [];
        this.eventsByDate = {};
        return;
      }
      this.events = Array.isArray(result.events) ? result.events : [];
      const grouped = {};
      for (const event of this.events) {
        const eventDate = new Date(event.start);
        if (Number.isNaN(eventDate.getTime())) continue;
        const key = dateKey(eventDate);
        (grouped[key] ||= []).push({ ...event, localDate: eventDate });
      }
      for (const key of Object.keys(grouped)) {
        grouped[key].sort((left, right) => left.localDate - right.localDate);
      }
      this.eventsByDate = grouped;
    } catch (error) {
      this.error = error?.message || "Failed to load calendar events";
      this.events = [];
      this.eventsByDate = {};
    } finally {
      this.loading = false;
    }
  },

  formatEventTime(event) {
    const eventDate = event?.localDate || new Date(event?.start);
    if (Number.isNaN(eventDate.getTime())) return "";
    return eventDate.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  },

  async openDayCreate(targetDateKey, hour = DEFAULT_CREATE_HOUR) {
    const { store: schedulerStore } = await import("/components/modals/scheduler/scheduler-store.js");
    window.openModal("modals/scheduler/scheduler-modal.html");
    globalThis.setTimeout(async () => {
      await schedulerStore.startCreateTask?.();
      if (targetDateKey && schedulerStore.editingTask) {
        const [year, month, day] = targetDateKey.split("-").map(Number);
        if (year && month && day) {
          const defaultTime = new Date(year, month - 1, day, hour, 0, 0);
          schedulerStore.editingTask.type = "planned";
          schedulerStore.editingTask.plan ||= { todo: [], in_progress: null, done: [] };
          schedulerStore.editingTask.plan.todo = [toUserWallClockISOString(defaultTime)];
        }
      }
    }, 150);
  },

  async openHourCreate(targetDateKey, hour) {
    await this.openDayCreate(targetDateKey, hour);
  },

  async openEvent(event) {
    if (!event?.task_uuid) return;
    const { store: schedulerStore } = await import("/components/modals/scheduler/scheduler-store.js");
    window.openModal("modals/scheduler/scheduler-modal.html");
    globalThis.setTimeout(async () => {
      await schedulerStore.fetchTasks?.({ manual: true });
      await schedulerStore.startEditTask?.(event.task_uuid);
    }, 150);
  },
};

const store = createStore("calendar", model);

export { store };

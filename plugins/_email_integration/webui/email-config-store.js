import { createStore } from "/js/AlpineStore.js";
import * as API from "/js/api.js";

const API_BASE = "/plugins/_email_integration";
const GMAIL_APP_PASSWORDS_URL = "https://support.google.com/mail/answer/185833?hl=en";
const PRESETS = {
  "": {
    label: "Choose a provider",
    account_type: "imap",
    imap_server: "",
    imap_port: 993,
    smtp_server: "",
    smtp_port: 587,
  },
  gmail: {
    label: "Gmail",
    account_type: "imap",
    imap_server: "imap.gmail.com",
    imap_port: 993,
    smtp_server: "smtp.gmail.com",
    smtp_port: 587,
  },
  icloud: {
    label: "iCloud Mail",
    account_type: "imap",
    imap_server: "imap.mail.me.com",
    imap_port: 993,
    smtp_server: "smtp.mail.me.com",
    smtp_port: 587,
  },
  microsoft365: {
    label: "Outlook / Microsoft 365",
    account_type: "imap",
    imap_server: "outlook.office365.com",
    imap_port: 993,
    smtp_server: "smtp.office365.com",
    smtp_port: 587,
  },
  yahoo: {
    label: "Yahoo Mail",
    account_type: "imap",
    imap_server: "imap.mail.yahoo.com",
    imap_port: 993,
    smtp_server: "smtp.mail.yahoo.com",
    smtp_port: 587,
  },
  exchange: {
    label: "Exchange",
    account_type: "exchange",
    imap_server: "outlook.office365.com",
    imap_port: 993,
    smtp_server: "smtp.office365.com",
    smtp_port: 587,
  },
  "custom-imap": {
    label: "Custom IMAP",
    account_type: "imap",
    imap_server: "",
    imap_port: 993,
    smtp_server: "",
    smtp_port: 587,
  },
};

const PROVIDER_OPTIONS = [
  {
    value: "gmail",
    label: "Gmail",
    hint: "Google app password",
    logo: "gmail",
    logoText: "M",
  },
  {
    value: "icloud",
    label: "iCloud Mail",
    hint: "Apple app-specific password",
    logo: "icloud",
    logoText: "cloud",
  },
  {
    value: "microsoft365",
    label: "Outlook / Microsoft 365",
    hint: "Microsoft mailbox preset",
    logo: "microsoft365",
    logoText: "",
  },
  {
    value: "yahoo",
    label: "Yahoo Mail",
    hint: "Yahoo app password",
    logo: "yahoo",
    logoText: "Y!",
  },
  {
    value: "exchange",
    label: "Exchange",
    hint: "Organization Exchange server",
    logo: "exchange",
    logoText: "X",
  },
  {
    value: "custom-imap",
    label: "Custom IMAP",
    hint: "Manual server settings",
    logo: "custom-imap",
    logoText: "dns",
  },
];

function ensureConfig(config) {
  if (!config || typeof config !== "object") return;
  if (!Array.isArray(config.handlers)) config.handlers = [];
}

export const store = createStore("emailConfig", {
  config: null,
  context: null,
  editing: null,
  testing: null,
  testResults: null,
  testResultsFor: null,
  providerPickerOpen: null,
  guideOpen: false,
  didInit: false,
  projects: [],
  modelPresets: [],
  presets: PRESETS,

  get providerOptions() {
    return PROVIDER_OPTIONS;
  },

  get handlers() {
    ensureConfig(this.config);
    return Array.isArray(this.config?.handlers) ? this.config.handlers : [];
  },

  async init(config, context = null) {
    if (!config || typeof config !== "object") return;

    this.config = config || null;
    this.context = context;
    this.didInit = false;
    ensureConfig(this.config);
    this.editing = this.handlers.length === 1 ? 0 : null;
    this.testing = null;
    this.testResults = null;
    this.testResultsFor = null;
    this.providerPickerOpen = null;
    this.guideOpen = this.handlers.length === 0 && window.innerWidth > 720;
    if (this.handlers.length === 0) this._startInitialHandlerFlow();
    if (this.editing !== null && !this.hasProvider(this.handlers[this.editing])) {
      this.providerPickerOpen = this.editing;
    }
    this.didInit = true;

    const [projectsResult, presetsResult] = await Promise.allSettled([
      API.callJsonApi("projects", { action: "list" }),
      API.callJsonApi("/plugins/_model_config/model_presets", { action: "get" }),
    ]);

    this.projects = projectsResult.status === "fulfilled" ? (projectsResult.value.data || []) : [];
    this.modelPresets = presetsResult.status === "fulfilled" && Array.isArray(presetsResult.value.presets)
      ? presetsResult.value.presets
      : [];
  },

  cleanup() {
    this.config = null;
    this.context = null;
    this.editing = null;
    this.testing = null;
    this.testResults = null;
    this.testResultsFor = null;
    this.providerPickerOpen = null;
    this.guideOpen = false;
    this.didInit = false;
  },

  newHandler() {
    return {
      name: "",
      enabled: false,
      provider: "",
      account_type: "imap",
      imap_server: "",
      imap_port: 993,
      smtp_server: "",
      smtp_port: 587,
      username: "",
      password: "",
      poll_mode: "seconds",
      poll_interval_seconds: 60,
      poll_interval_cron: "*/2 * * * *",
      process_unread_days: 0,
      sender_whitelist: [],
      project: "",
      dispatcher_model: "utility",
      chat_model_preset: "",
      dispatcher_instructions: "",
      agent_instructions: "",
    };
  },

  addHandler() {
    ensureConfig(this.config);
    this.config.handlers.push(this.newHandler());
    this.editing = this.config.handlers.length - 1;
    this.providerPickerOpen = this.editing;
    this.testResults = null;
    this.testResultsFor = null;
  },

  removeHandler(idx) {
    this.handlers.splice(idx, 1);
    if (this.editing === idx) this.editing = null;
    if (this.editing !== null && this.editing > idx) this.editing -= 1;
    if (this.providerPickerOpen === idx) this.providerPickerOpen = null;
    if (this.providerPickerOpen !== null && this.providerPickerOpen > idx) this.providerPickerOpen -= 1;
    if (this.testResultsFor === idx) {
      this.testResults = null;
      this.testResultsFor = null;
    }
  },

  toggleEditing(idx) {
    this.editing = this.editing === idx ? null : idx;
    if (this.editing === null) {
      this.providerPickerOpen = null;
    } else if (!this.hasProvider(this.handlers[idx])) {
      this.providerPickerOpen = idx;
    }
    if (this.testResultsFor !== idx) {
      this.testResults = null;
      this.testResultsFor = null;
    }
  },

  providerValue(handler) {
    if (!handler || typeof handler !== "object") return "";
    const explicitProvider = String(handler.provider || "").trim();
    if (explicitProvider && this.presets[explicitProvider]) return explicitProvider;

    const incoming = String(handler.imap_server || "").trim().toLowerCase();
    const outgoing = String(handler.smtp_server || "").trim().toLowerCase();
    const accountType = handler.account_type || "imap";

    if (!incoming && !outgoing && !handler.username && !handler.password) return "";
    if (accountType === "exchange") return "exchange";
    if (incoming === "imap.gmail.com" || outgoing === "smtp.gmail.com") return "gmail";
    if (incoming === "imap.mail.me.com" || outgoing === "smtp.mail.me.com") return "icloud";
    if (incoming === "outlook.office365.com" || outgoing === "smtp.office365.com") return "microsoft365";
    if (incoming === "imap.mail.yahoo.com" || outgoing === "smtp.mail.yahoo.com") return "yahoo";
    return "custom-imap";
  },

  hasProvider(handler) {
    return Boolean(this.providerValue(handler));
  },

  showProviderChoices(handler, idx) {
    return !this.hasProvider(handler) || this.providerPickerOpen === idx;
  },

  changeProvider(idx) {
    this.providerPickerOpen = this.providerPickerOpen === idx ? null : idx;
  },

  providerLabel(value) {
    return this.presets[value]?.label || "Custom IMAP";
  },

  selectProvider(handler, value, idx = null) {
    this.applyProvider(handler, value);
    this.providerPickerOpen = null;
    this.testResults = null;
    this.testResultsFor = null;
    if (idx !== null) this.editing = idx;
  },

  applyProvider(handler, value) {
    const preset = this.presets[value];
    if (!preset) return;
    const previous = this.providerValue(handler);

    handler.account_type = preset.account_type;
    handler.provider = value;

    if (value === "custom-imap") {
      if (previous !== "custom-imap") {
        handler.imap_server = "";
        handler.smtp_server = "";
      }
      if (!handler.imap_port) handler.imap_port = 993;
      if (!handler.smtp_port) handler.smtp_port = 587;
      return;
    }

    handler.imap_server = preset.imap_server;
    handler.imap_port = preset.imap_port;
    handler.smtp_server = preset.smtp_server;
    handler.smtp_port = preset.smtp_port;
  },

  providerHint(handler) {
    const provider = this.providerValue(handler);
    if (provider === "gmail") return "Use a Google App Password. A regular Gmail password usually will not work here.";
    if (provider === "icloud") return "Use an app-specific password from your Apple account settings.";
    if (provider === "microsoft365") return "Most Outlook and Microsoft 365 inboxes work with this preset.";
    if (provider === "yahoo") return "Yahoo Mail usually works best with an app password.";
    if (provider === "exchange") return "Choose Exchange only if your organization requires it. For the simplest setup, try Outlook / Microsoft 365 first.";
    if (provider === "custom-imap") return "Bring your own incoming and outgoing mail server details.";
    return "How to start: turn on inbox, pick your provider, then add your email address and password.";
  },

  providerHelpUrl(handler) {
    return this.providerValue(handler) === "gmail" ? GMAIL_APP_PASSWORDS_URL : "";
  },

  providerHelpLabel(handler) {
    if (this.providerValue(handler) !== "gmail") return "";
    return "Google's guide to create a Gmail App Password";
  },

  showManualServers(handler) {
    return this.providerValue(handler) === "custom-imap";
  },

  showExchangeServer(handler) {
    return this.providerValue(handler) === "exchange";
  },

  incomingLabel(handler) {
    return this.showExchangeServer(handler) ? "Exchange server" : "Incoming mail server";
  },

  incomingDescription(handler) {
    return this.showExchangeServer(handler)
      ? "The Exchange or Microsoft 365 server for this inbox"
      : "The IMAP server for incoming mail";
  },

  incomingPlaceholder(handler) {
    return this.showExchangeServer(handler) ? "outlook.office365.com" : "imap.your-provider.com";
  },

  scheduleLabel(handler) {
    const value = this.frequencyValue(handler);
    if (value === "15") return "Checks every 15 seconds";
    if (value === "30") return "Checks every 30 seconds";
    if (value === "60") return "Checks every minute";
    if (value === "300") return "Checks every 5 minutes";
    if (value === "900") return "Checks every 15 minutes";
    return "Uses a custom schedule";
  },

  frequencyValue(handler) {
    if (handler.poll_mode !== "seconds") return "custom";
    const seconds = Number(handler.poll_interval_seconds || 0);
    if ([15, 30, 60, 300, 900].includes(seconds)) return String(seconds);
    return "custom";
  },

  applyFrequency(handler, value) {
    if (value === "custom") {
      if (handler.poll_mode !== "cron") handler.poll_mode = "seconds";
      if (!handler.poll_interval_seconds) handler.poll_interval_seconds = 60;
      return;
    }
    handler.poll_mode = "seconds";
    handler.poll_interval_seconds = Number(value);
  },

  frequencyHint(handler) {
    return this.frequencyValue(handler) === "custom"
      ? "You are using a custom schedule. You can change the raw timing in Advanced."
      : this.scheduleLabel(handler);
  },

  whitelistText(handler) {
    return (handler.sender_whitelist || []).join(", ");
  },

  setWhitelist(handler, value) {
    handler.sender_whitelist = value
      .split(",")
      .map((entry) => entry.trim())
      .filter((entry) => entry);
  },

  slugify(value) {
    return String(value || "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "");
  },

  maybeAutoname(handler) {
    const current = String(handler.name || "").trim();
    if (current && !/^handler_\d+$/.test(current)) return;
    const email = String(handler.username || "").trim();
    const localPart = email.split("@")[0] || "";
    const nextName = this.slugify(localPart);
    if (nextName) handler.name = nextName;
  },

  missingBits(handler) {
    const missing = [];
    const provider = this.providerValue(handler);
    if (!provider) missing.push("provider");
    if (!handler.username) missing.push("email address");
    if (!handler.password) missing.push("password");
    if ((this.showManualServers(handler) || this.showExchangeServer(handler)) && !handler.imap_server) {
      missing.push(this.showExchangeServer(handler) ? "Exchange server" : "incoming server");
    }
    if (this.showManualServers(handler) && !handler.smtp_server) missing.push("outgoing server");
    return missing;
  },

  canTest(handler) {
    return this.missingBits(handler).length === 0;
  },

  statusLabel(handler) {
    if (!handler.username && !this.providerValue(handler)) return "New";
    if (handler.enabled && this.canTest(handler)) return "Live";
    if (this.canTest(handler)) return "Ready";
    return "Needs info";
  },

  statusTone(handler) {
    if (!handler.username && !this.providerValue(handler)) return "muted";
    if (handler.enabled && this.canTest(handler)) return "success";
    if (this.canTest(handler)) return "ready";
    return "warning";
  },

  handlerTitle(handler, idx) {
    return handler.username || handler.name || `Inbox ${idx + 1}`;
  },

  handlerSubtitle(handler) {
    const pieces = [];
    const provider = this.providerValue(handler);
    if (provider) pieces.push(this.providerLabel(provider));
    pieces.push(this.scheduleLabel(handler).replace("Checks ", ""));
    if (handler.project) pieces.push(`Project: ${handler.project}`);
    return pieces.join(" · ");
  },

  testButtonLabel(handler, idx) {
    if (this.testing === idx) return "Checking...";
    if (this.canTest(handler)) return "Check setup";
    return "Fill in the basics first";
  },

  testIntro(handler) {
    if (this.providerValue(handler) === "exchange") {
      return "We will check the inbox, check outgoing mail, then send a test email to this address.";
    }
    return "We will check incoming mail, check outgoing mail, then send a test email to this inbox.";
  },

  resultTitle(result) {
    return result.test || "Check";
  },

  resultMessage(result) {
    return result.message || (result.ok ? "Done." : "Something went wrong.");
  },

  _startInitialHandlerFlow() {
    this.addHandler();
    if (!this.context) return;
    const toComparableJson = typeof this.context._toComparableJson === "function"
      ? this.context._toComparableJson.bind(this.context)
      : JSON.stringify;
    this.context.settingsSnapshotJson = toComparableJson(this.context.settings);
  },

  async testConnection(idx) {
    const handler = this.handlers[idx];
    if (!handler || !this.canTest(handler)) return;

    this.testing = idx;
    this.testResults = null;
    this.testResultsFor = idx;

    try {
      this.testResults = await API.callJsonApi(`${API_BASE}/test_connection`, { handler });
    } catch (error) {
      this.testResults = {
        success: false,
        results: [{ test: "Connection", ok: false, message: String(error) }],
      };
    }

    this.testing = null;
  },
});

import { bindApiKeyInput, ensureMonitorApiKey } from "./monitor-auth.js";

const API_BASE = window.MONITOR_API_BASE || window.location.origin;
const apiKeyInput = document.getElementById("apiKeyInput");
const apiKeyMessage = document.getElementById("apiKeyMessage");
const missingApiKeyMessage = "Enter an API key to send authenticated requests.";
bindApiKeyInput(apiKeyInput, apiKeyMessage, missingApiKeyMessage);

const ALLOWED_SEVERITIES_BY_EVENT_TYPE = {
  problem: ["critical", "warning"],
  ok: ["info"],
  enable: ["info"],
  disable: ["info"],
};

const STALE_INTERVAL_RE = /^(?:\d+[dhm])+$/;
const STALE_INTERVAL_PART_RE = /(\d+)([dhm])/g;
const DEFAULT_ACK_MESSAGE = "Investigating issue.";

function toUtcIso(value) {
  if (!value) return null;
  const local = new Date(value);
  return local.toISOString();
}

function randomId(prefix) {
  return `${prefix}-${Date.now()}`;
}

function compareStoreIdsByNumericSuffix(a, b) {
  const aText = String(a || "");
  const bText = String(b || "");
  const aMatch = aText.match(/(\d+)(?!.*\d)/);
  const bMatch = bText.match(/(\d+)(?!.*\d)/);

  if (aMatch && bMatch) {
    const aNum = Number(aMatch[1]);
    const bNum = Number(bMatch[1]);
    if (aNum !== bNum) return aNum - bNum;
  }

  return aText.localeCompare(bText, undefined, { numeric: true, sensitivity: "base" });
}

function setSelectOptions(select, values, preferredValue = null) {
  const unique = Array.from(new Set((values || []).map((value) => String(value || "").trim()).filter(Boolean)));
  if (!unique.length) {
    select.innerHTML = '<option value="">(none available)</option>';
    select.value = "";
    return;
  }

  select.innerHTML = unique
    .map((value) => `<option value="${value}">${value}</option>`)
    .join("");

  if (preferredValue && unique.includes(preferredValue)) {
    select.value = preferredValue;
  } else if (unique.includes(select.value)) {
    // Keep current selection when possible.
  } else {
    select.value = unique[0];
  }
}

async function fetchAvailableStores() {
  const storesResponse = await fetch(`${API_BASE}/api/v1/status/stores`);
  if (storesResponse.ok) {
    const stores = await storesResponse.json();
    return stores
      .map((store) => store.store_id)
      .filter(Boolean)
      .sort(compareStoreIdsByNumericSuffix);
  }

  const bootstrapResponse = await fetch(`${API_BASE}/api/v1/bootstrap`);
  if (!bootstrapResponse.ok) return [];
  const bootstrap = await bootstrapResponse.json();
  return (bootstrap.statuses || [])
    .map((status) => status.store_id)
    .filter(Boolean)
    .sort(compareStoreIdsByNumericSuffix);
}

async function fetchComponentsForStore(storeId) {
  if (!storeId) return [];

  const componentsResponse = await fetch(`${API_BASE}/api/v1/status/stores/${encodeURIComponent(storeId)}/components`);
  if (componentsResponse.ok) {
    const components = await componentsResponse.json();
    return components
      .map((component) => component.component)
      .filter(Boolean)
      .sort((a, b) => a.localeCompare(b));
  }

  const bootstrapResponse = await fetch(`${API_BASE}/api/v1/bootstrap`);
  if (!bootstrapResponse.ok) return [];
  const bootstrap = await bootstrapResponse.json();
  return (bootstrap.statuses || [])
    .filter((status) => status.store_id === storeId)
    .map((status) => status.component)
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b));
}

async function hydrateStoreAndComponentSelectors() {
  const storeSelect = document.getElementById("storeId");
  const componentSelect = document.getElementById("component");
  const preferredStore = storeSelect.value;
  const preferredComponent = componentSelect.value;

  const stores = await fetchAvailableStores();
  setSelectOptions(storeSelect, stores, preferredStore || "store-104");

  const components = await fetchComponentsForStore(storeSelect.value);
  setSelectOptions(componentSelect, components, preferredComponent || "payments");
}

async function refreshComponentsForSelectedStore() {
  const storeSelect = document.getElementById("storeId");
  const componentSelect = document.getElementById("component");
  const currentComponent = componentSelect.value;
  const components = await fetchComponentsForStore(storeSelect.value);
  setSelectOptions(componentSelect, components, currentComponent);
}

function defaultDedupKey() {
  const store = document.getElementById("storeId").value;
  const component = document.getElementById("component").value;
  const eventType = document.getElementById("eventType").value;
  return `${store}_${component}_${eventType}`.toUpperCase();
}

function metadataFromText() {
  const raw = document.getElementById("metadataInput").value;
  const metadata = {};
  const lines = raw.split(/\r?\n/);

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i].trim();
    if (!line) continue;

    const separator = line.indexOf("=");
    if (separator <= 0) {
      throw new Error(`Invalid metadata line ${i + 1}: use key=value format.`);
    }

    const key = line.slice(0, separator).trim();
    const value = line.slice(separator + 1).trim();
    if (!key) {
      throw new Error(`Invalid metadata line ${i + 1}: key cannot be empty.`);
    }

    metadata[key] = value;
  }

  return metadata;
}

function parseStaleIntervalText() {
  const raw = document.getElementById("staleInterval").value.trim().toLowerCase();
  if (!raw) return null;
  if (!STALE_INTERVAL_RE.test(raw)) {
    throw new Error("Invalid stale interval. Use d/h/m format like 2d5h10m, 5h, or 30m.");
  }
  STALE_INTERVAL_PART_RE.lastIndex = 0;
  let match;
  while ((match = STALE_INTERVAL_PART_RE.exec(raw)) !== null) {
    if (Number(match[1]) <= 0) {
      throw new Error("Invalid stale interval. Segment values must be positive integers.");
    }
  }
  return raw;
}

function syncSeverityOptions() {
  const eventType = document.getElementById("eventType").value;
  const severitySelect = document.getElementById("severity");
  const current = severitySelect.value;
  const allowed = ALLOWED_SEVERITIES_BY_EVENT_TYPE[eventType] || ["info"];

  severitySelect.innerHTML = allowed
    .map((severity) => `<option value="${severity}">${severity}</option>`)
    .join("");
  severitySelect.value = allowed.includes(current) ? current : allowed[0];
}

function setSenderResultOutput(text) {
  document.getElementById("senderResultOutput").textContent = text;
}

function showSenderResult(payload, responseText) {
  const lines = [
    "Payload Preview",
    "---------------",
    JSON.stringify(payload, null, 2),
    "",
    "API Response",
    "------------",
    responseText,
  ];

  setSenderResultOutput(lines.join("\n"));
  const modal = document.getElementById("senderResultModal");
  if (!modal.open) modal.showModal();
}

async function hydrateAckSelector() {
  const [eventsResp, acksResp] = await Promise.all([
    fetch(`${API_BASE}/api/v1/bootstrap`),
    fetch(`${API_BASE}/api/v1/acks`),
  ]);

  const eventsPayload = eventsResp.ok ? await eventsResp.json() : { recent_events: [] };
  const activeAcks = new Set();

  if (acksResp.ok) {
    const ackPayload = await acksResp.json();
    for (const ack of ackPayload) activeAcks.add(ack.event_id);
  }

  const options = (eventsPayload.recent_events || [])
    .filter((event) => !activeAcks.has(event.event_id))
    .slice(0, 250)
    .map((event) => `<option value="${event.event_id}">${event.event_id} (${event.store_id}/${event.component})</option>`);

  const select = document.getElementById("ackEventId");
  select.innerHTML = options.join("");
}

async function sendEventFromForm() {
  const payload = {
    event_id: randomId("evt-ui"),
    dedup_key: defaultDedupKey(),
    store_id: document.getElementById("storeId").value,
    component: document.getElementById("component").value,
    event_type: document.getElementById("eventType").value,
    severity: document.getElementById("severity").value,
    message: document.getElementById("eventMessage").value.trim(),
    source: document.getElementById("source").value,
    metadata: metadataFromText(),
  };

  const staleInterval = parseStaleIntervalText();
  if (staleInterval) payload.stale_interval = staleInterval;
  const apiKey = ensureMonitorApiKey({
    inputEl: apiKeyInput,
    messageEl: apiKeyMessage,
    message: missingApiKeyMessage,
  });

  const response = await fetch(`${API_BASE}/api/v1/events`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Monitor-Key": apiKey,
    },
    body: JSON.stringify(payload),
  });

  const body = await response.text();
  showSenderResult(payload, `HTTP ${response.status}\n${body}`);
  await hydrateAckSelector();
}

async function sendAckFromForm() {
  const eventId = document.getElementById("ackEventId").value;
  const expiresAt = toUtcIso(document.getElementById("ackExpiresAt").value);
  const payload = {
    event_id: eventId,
    ack_message: document.getElementById("ackMessage").value.trim(),
    ack_by: document.getElementById("ackBy").value,
    expires_at: expiresAt,
  };
  const apiKey = ensureMonitorApiKey({
    inputEl: apiKeyInput,
    messageEl: apiKeyMessage,
    message: missingApiKeyMessage,
  });

  const response = await fetch(`${API_BASE}/api/v1/acks`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Monitor-Key": apiKey,
    },
    body: JSON.stringify(payload),
  });

  const body = await response.text();
  showSenderResult(payload, `HTTP ${response.status}\n${body}`);
  await hydrateAckSelector();
}

function resetAckDefaults() {
  document.getElementById("ackBy").value = "operator-console";
  document.getElementById("ackMessage").value = DEFAULT_ACK_MESSAGE;
  const defaultExpiry = new Date(Date.now() + 30 * 60000);
  const localIso = new Date(defaultExpiry.getTime() - defaultExpiry.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
  document.getElementById("ackExpiresAt").value = localIso;
}

async function resetSenderToDefaults() {
  const modeSelect = document.getElementById("senderMode");
  const eventTypeSelect = document.getElementById("eventType");
  const sourceSelect = document.getElementById("source");
  const staleIntervalInput = document.getElementById("staleInterval");
  const metadataInput = document.getElementById("metadataInput");
  const eventMessage = document.getElementById("eventMessage");
  const eventForm = document.getElementById("eventModeForm");
  const ackForm = document.getElementById("ackModeForm");

  modeSelect.value = "event";
  eventForm.classList.remove("hidden");
  ackForm.classList.add("hidden");

  eventTypeSelect.value = "problem";
  syncSeverityOptions();
  sourceSelect.value = "test-sender";
  staleIntervalInput.value = "";
  metadataInput.value = "";
  eventMessage.value = "";
  resetAckDefaults();

  await hydrateStoreAndComponentSelectors();
  await hydrateAckSelector();
}

function wireSender() {
  const modeSelect = document.getElementById("senderMode");
  const eventForm = document.getElementById("eventModeForm");
  const ackForm = document.getElementById("ackModeForm");
  const sendBtn = document.getElementById("sendTestMessageBtn");
  const eventTypeSelect = document.getElementById("eventType");
  const storeSelect = document.getElementById("storeId");
  const resultOkBtn = document.getElementById("senderResultOkBtn");
  const resultModal = document.getElementById("senderResultModal");

  modeSelect.addEventListener("change", () => {
    const eventMode = modeSelect.value === "event";
    eventForm.classList.toggle("hidden", !eventMode);
    ackForm.classList.toggle("hidden", eventMode);
  });

  eventTypeSelect.addEventListener("change", syncSeverityOptions);
  eventTypeSelect.addEventListener("input", syncSeverityOptions);
  storeSelect.addEventListener("change", async () => {
    try {
      await refreshComponentsForSelectedStore();
    } catch (error) {
      setSenderResponse(String(error));
    }
  });

  sendBtn.addEventListener("click", async () => {
    try {
      if (modeSelect.value === "event") {
        await sendEventFromForm();
      } else {
        await sendAckFromForm();
      }
    } catch (error) {
      showSenderResult({}, error?.message || String(error));
    }
  });

  resultOkBtn.addEventListener("click", async () => {
    resultModal.close();
    try {
      await resetSenderToDefaults();
    } catch (error) {
      showSenderResult({}, String(error));
    }
  });
}

async function start() {
  wireSender();
  syncSeverityOptions();
  resetAckDefaults();
  await hydrateStoreAndComponentSelectors();
  await hydrateAckSelector();
}

start().catch((error) => {
  console.error(error);
  showSenderResult({}, String(error));
});

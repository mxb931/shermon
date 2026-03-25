const API_BASE = window.MONITOR_API_BASE || "http://localhost:8000";

const ALLOWED_SEVERITIES_BY_EVENT_TYPE = {
  problem: ["critical", "warning"],
  ok: ["info"],
  enable: ["info"],
  disable: ["info"],
};

const STALE_INTERVAL_RE = /^(?:\d+[dhm])+$/;
const STALE_INTERVAL_PART_RE = /(\d+)([dhm])/g;

function toUtcIso(value) {
  if (!value) return null;
  const local = new Date(value);
  return local.toISOString();
}

function randomId(prefix) {
  return `${prefix}-${Date.now()}`;
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

function setPreview(payload) {
  document.getElementById("payloadPreview").textContent = JSON.stringify(payload, null, 2);
}

function setSenderResponse(text) {
  document.getElementById("senderResponse").textContent = text;
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

  setPreview(payload);

  const response = await fetch(`${API_BASE}/api/v1/events`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Monitor-Key": document.getElementById("apiKeySelect").value,
    },
    body: JSON.stringify(payload),
  });

  const body = await response.text();
  setSenderResponse(`HTTP ${response.status}\n${body}`);
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
  setPreview(payload);

  const response = await fetch(`${API_BASE}/api/v1/acks`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Monitor-Key": document.getElementById("apiKeySelect").value,
    },
    body: JSON.stringify(payload),
  });

  const body = await response.text();
  setSenderResponse(`HTTP ${response.status}\n${body}`);
  await hydrateAckSelector();
}

function wireSender() {
  const modeSelect = document.getElementById("senderMode");
  const eventForm = document.getElementById("eventModeForm");
  const ackForm = document.getElementById("ackModeForm");
  const sendBtn = document.getElementById("sendTestMessageBtn");
  const eventTypeSelect = document.getElementById("eventType");

  modeSelect.addEventListener("change", () => {
    const eventMode = modeSelect.value === "event";
    eventForm.classList.toggle("hidden", !eventMode);
    ackForm.classList.toggle("hidden", eventMode);
  });

  eventTypeSelect.addEventListener("change", syncSeverityOptions);
  eventTypeSelect.addEventListener("input", syncSeverityOptions);

  sendBtn.addEventListener("click", async () => {
    try {
      if (modeSelect.value === "event") {
        await sendEventFromForm();
      } else {
        await sendAckFromForm();
      }
    } catch (error) {
      setSenderResponse(String(error));
    }
  });
}

async function start() {
  wireSender();
  syncSeverityOptions();
  await hydrateAckSelector();
}

start().catch((error) => {
  console.error(error);
  setSenderResponse(String(error));
});

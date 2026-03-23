const API_BASE = window.MONITOR_API_BASE || "http://localhost:8000";

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

function metadataFromTemplate() {
  const raw = document.getElementById("metadataTemplate").value;
  return JSON.parse(raw);
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
    metadata: metadataFromTemplate(),
  };

  const interval = document.getElementById("heartbeatInterval").value;
  if (interval) payload.expected_green_interval_seconds = Number(interval);

  const expiresAt = toUtcIso(document.getElementById("eventExpiresAt").value);
  if (expiresAt) payload.expires_at = expiresAt;

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

  modeSelect.addEventListener("change", () => {
    const eventMode = modeSelect.value === "event";
    eventForm.classList.toggle("hidden", !eventMode);
    ackForm.classList.toggle("hidden", eventMode);
  });

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
  await hydrateAckSelector();
}

start().catch((error) => {
  console.error(error);
  setSenderResponse(String(error));
});

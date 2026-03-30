import { ensureMonitorApiKey, getMissingMonitorApiKeyMessage } from "./monitor-auth.js";

const API_BASE = window.MONITOR_API_BASE || window.location.origin;
const defaultWsUrl = new URL("/ws/updates", window.location.origin);
defaultWsUrl.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
const WS_BASE = window.MONITOR_WS_BASE || defaultWsUrl.toString().replace(/\/$/, "");

const ackList = document.getElementById("ackList");
const connectionBadge = document.getElementById("connectionBadge");
const state = {
  acks: new Map(),
  reconnectAttempt: 0,
};

function updateConnectionBadge(mode) {
  connectionBadge.className = `badge ${mode}`;
  connectionBadge.textContent = mode;
}

function reconnectDelay(attempt) {
  const raw = Math.min(1000 * (2 ** attempt), 15000);
  return raw + Math.floor(Math.random() * 400);
}

function renderAckList() {
  const rows = Array.from(state.acks.values()).map((ack) => {
    const expires = new Date(ack.expires_at);
    const remainingMs = expires.getTime() - Date.now();
    const remainingMin = Math.max(0, Math.ceil(remainingMs / 60000));
    return `
      <li class="incident-item">
        <strong>${ack.store_id}/${ack.component}</strong><br />
        ${ack.ack_message}<br />
        <small>event: ${ack.event_id} | by: ${ack.ack_by || "unknown"} | expires in: ${remainingMin}m</small><br />
        <button class="ack-btn" data-expire-event="${ack.event_id}">Expire now</button>
      </li>
    `;
  });
  ackList.innerHTML = rows.join("");
}

async function loadAcks() {
  const response = await fetch(`${API_BASE}/api/v1/acks`);
  if (!response.ok) throw new Error("Failed to load acknowledgements");
  const payload = await response.json();
  state.acks.clear();
  for (const ack of payload) {
    state.acks.set(ack.event_id, ack);
  }
  renderAckList();
}

function connectWebSocket() {
  updateConnectionBadge("reconnecting");
  const ws = new WebSocket(WS_BASE);

  ws.onopen = () => {
    state.reconnectAttempt = 0;
    updateConnectionBadge("connected");
    ws.send("ping");
    setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send("ping");
    }, 15000);
  };

  ws.onmessage = (message) => {
    const payload = JSON.parse(message.data);
    if (payload.kind === "ack_update" && payload.ack) {
      state.acks.set(payload.ack.event_id, payload.ack);
      renderAckList();
    }
    if (payload.kind === "ack_expired" && payload.event_id) {
      state.acks.delete(payload.event_id);
      renderAckList();
    }
  };

  ws.onclose = () => {
    updateConnectionBadge("stale");
    const delay = reconnectDelay(state.reconnectAttempt);
    state.reconnectAttempt += 1;
    setTimeout(connectWebSocket, delay);
  };

  ws.onerror = () => ws.close();
}

function wireExpireButtons() {
  ackList.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const eventId = target.getAttribute("data-expire-event");
    if (!eventId) return;

    try {
      const apiKey = ensureMonitorApiKey({
        message: getMissingMonitorApiKeyMessage("expire acknowledgements"),
      });
      const response = await fetch(`${API_BASE}/api/v1/acks/${eventId}`, {
        method: "DELETE",
        headers: { "X-Monitor-Key": apiKey },
      });

      if (!response.ok) {
        const detail = (await response.text()).trim();
        throw new Error(detail || `Failed to expire acknowledgement (HTTP ${response.status}).`);
      }

      state.acks.delete(eventId);
      renderAckList();
    } catch (error) {
      window.alert(error?.message || String(error));
    }
  });
}

async function start() {
  wireExpireButtons();
  await loadAcks();
  connectWebSocket();
  setInterval(renderAckList, 60000);
}

start().catch((error) => {
  console.error(error);
  updateConnectionBadge("stale");
});

const API_BASE = window.MONITOR_API_BASE || "http://localhost:8000";
const WS_BASE = window.MONITOR_WS_BASE || "ws://localhost:8000/ws/updates";

const state = {
  statuses: new Map(),
  incidents: [],
  socket: null,
  reconnectAttempt: 0,
};

const statusGrid = document.getElementById("statusGrid");
const incidentList = document.getElementById("incidentList");
const connectionBadge = document.getElementById("connectionBadge");

function updateConnectionBadge(mode) {
  connectionBadge.className = `badge ${mode}`;
  connectionBadge.textContent = mode;
}

function renderSummary() {
  let green = 0;
  let yellow = 0;
  let red = 0;

  for (const status of state.statuses.values()) {
    if (status.status_color === "green") green += 1;
    if (status.status_color === "yellow") yellow += 1;
    if (status.status_color === "red") red += 1;
  }

  document.getElementById("greenCount").textContent = String(green);
  document.getElementById("yellowCount").textContent = String(yellow);
  document.getElementById("redCount").textContent = String(red);
}

function renderStatusGrid() {
  const cards = [];
  for (const status of state.statuses.values()) {
    cards.push(`
      <article class="tile status ${status.status_color}">
        <div class="title">${status.store_id} / ${status.component}</div>
        <div>${status.status_color.toUpperCase()} | active: ${status.active_incident_count}</div>
        <div class="meta">${new Date(status.last_changed_at).toLocaleString()}</div>
        <div>${status.last_message || "No incidents yet"}</div>
      </article>
    `);
  }
  statusGrid.innerHTML = cards.join("");
}

function renderIncidentList() {
  const rows = state.incidents.slice(0, 150).map((event) => `
    <li class="incident-item">
      <strong>[${event.severity}]</strong> ${event.store_id}/${event.component} ${event.event_type}<br />
      ${event.message}<br />
      <small>${new Date(event.happened_at).toLocaleString()} | ${event.source}</small>
    </li>
  `);
  incidentList.innerHTML = rows.join("");
}

function renderAll() {
  renderSummary();
  renderStatusGrid();
  renderIncidentList();
}

async function loadBootstrap() {
  const response = await fetch(`${API_BASE}/api/v1/bootstrap`);
  if (!response.ok) throw new Error("Failed bootstrap");
  const payload = await response.json();

  for (const status of payload.statuses) {
    const key = `${status.store_id}:${status.component}`;
    state.statuses.set(key, status);
  }

  state.incidents = payload.recent_events;
  renderAll();
}

function applyRealtimeUpdate(payload) {
  if (!payload?.status || !payload?.event) return;

  const key = `${payload.status.store_id}:${payload.status.component}`;
  state.statuses.set(key, payload.status);
  state.incidents.unshift(payload.event);
  if (state.incidents.length > 1000) {
    state.incidents.length = 1000;
  }
  renderAll();
}

function reconnectDelay(attempt) {
  const raw = Math.min(1000 * (2 ** attempt), 15000);
  return raw + Math.floor(Math.random() * 400);
}

function connectWebSocket() {
  updateConnectionBadge("reconnecting");
  const ws = new WebSocket(WS_BASE);
  state.socket = ws;

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
    applyRealtimeUpdate(payload);
  };

  ws.onclose = () => {
    updateConnectionBadge("stale");
    const delay = reconnectDelay(state.reconnectAttempt);
    state.reconnectAttempt += 1;
    setTimeout(connectWebSocket, delay);
  };

  ws.onerror = () => ws.close();
}

async function start() {
  try {
    await loadBootstrap();
  } catch (error) {
    console.error(error);
  }
  connectWebSocket();
}

start();

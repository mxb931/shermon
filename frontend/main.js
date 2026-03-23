const API_BASE = window.MONITOR_API_BASE || "http://localhost:8000";
const WS_BASE = window.MONITOR_WS_BASE || "ws://localhost:8000/ws/updates";

const state = {
  statuses: new Map(),
  incidents: [],
  acks: new Map(),
  socket: null,
  reconnectAttempt: 0,
  pendingAckEventId: null,
  selectedStoreId: null,
  entityAlertsContext: null,
  pingTimerId: null,
};

const statusGrid = document.getElementById("statusGrid");
const incidentList = document.getElementById("incidentList");
const connectionBadge = document.getElementById("connectionBadge");
const ackModal = document.getElementById("ackModal");
const entityStatusTitle = document.getElementById("entityStatusTitle");
const entityStatusHint = document.getElementById("entityStatusHint");
const entityBackBtn = document.getElementById("entityBackBtn");
const entityAlertsModal = document.getElementById("entityAlertsModal");
const entityAlertsSummary = document.getElementById("entityAlertsSummary");
const entityAlertsList = document.getElementById("entityAlertsList");

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function statusLabel(statusColor) {
  const labels = {
    green: "OK",
    yellow: "WARN",
    red: "CRITICAL",
    purple: "STALE",
    white: "DISABLED",
  };
  return labels[statusColor] || String(statusColor || "").toUpperCase();
}

function statusRank(statusColor) {
  const ranks = {
    red: 5,
    yellow: 4,
    purple: 3,
    green: 2,
    white: 1,
  };
  return ranks[statusColor] || 0;
}

function compareIncidentsByNewest(a, b) {
  const timeDiff = Date.parse(b.happened_at) - Date.parse(a.happened_at);
  if (!Number.isNaN(timeDiff) && timeDiff !== 0) return timeDiff;
  return b.event_id.localeCompare(a.event_id);
}

function sortIncidentsNewestFirst() {
  state.incidents.sort(compareIncidentsByNewest);
}

function updateConnectionBadge(mode) {
  connectionBadge.className = `badge ${mode}`;
  connectionBadge.textContent = mode;
}

function renderSummary() {
  const counts = { green: 0, yellow: 0, red: 0, purple: 0, white: 0 };

  for (const status of state.statuses.values()) {
    if (counts[status.status_color] !== undefined) {
      counts[status.status_color] += 1;
    }
  }

  document.getElementById("greenCount").textContent = String(counts.green);
  document.getElementById("yellowCount").textContent = String(counts.yellow);
  document.getElementById("redCount").textContent = String(counts.red);
  document.getElementById("purpleCount").textContent = String(counts.purple);
  document.getElementById("whiteCount").textContent = String(counts.white);
}

function buildStoreSummaries() {
  const grouped = new Map();
  for (const status of state.statuses.values()) {
    const summary = grouped.get(status.store_id) || {
      store_id: status.store_id,
      status_color: "white",
      active_incident_count: 0,
      component_count: 0,
    };

    if (statusRank(status.status_color) > statusRank(summary.status_color)) {
      summary.status_color = status.status_color;
    }
    summary.active_incident_count += status.active_incident_count;
    summary.component_count += 1;
    grouped.set(status.store_id, summary);
  }

  return Array.from(grouped.values()).sort((a, b) => {
    const colorDiff = statusRank(b.status_color) - statusRank(a.status_color);
    if (colorDiff !== 0) return colorDiff;
    return a.store_id.localeCompare(b.store_id);
  });
}

function getComponentsForSelectedStore() {
  if (!state.selectedStoreId) return [];
  return Array.from(state.statuses.values())
    .filter((status) => status.store_id === state.selectedStoreId)
    .sort((a, b) => {
      const colorDiff = statusRank(b.status_color) - statusRank(a.status_color);
      if (colorDiff !== 0) return colorDiff;
      return a.component.localeCompare(b.component);
    });
}

function renderStoreGrid() {
  const stores = buildStoreSummaries();
  entityStatusTitle.textContent = "Stores";
  entityStatusHint.textContent = "Select a store to view component health.";
  entityBackBtn.classList.add("hidden");

  if (!stores.length) {
    statusGrid.innerHTML = "<div class=\"meta\">No stores are reporting yet.</div>";
    return;
  }

  const cards = stores.map((store) => {
    const storeId = escapeHtml(store.store_id);
    const statusColor = escapeHtml(store.status_color);
    const label = escapeHtml(statusLabel(store.status_color));
    return `
      <article
        class="tile status status-button ${statusColor} clickable"
        data-store-id="${storeId}"
        tabindex="0"
        role="button"
        aria-label="Open components for ${storeId}"
      >
        <div class="eyebrow">Store</div>
        <div class="title">${storeId}</div>
        <div class="status-line">
          <span class="status-pill">${label}</span>
        </div>
        <div class="entity-metrics">
          <div class="metric"><span>Components</span><strong>${store.component_count}</strong></div>
          <div class="metric"><span>Active alerts</span><strong>${store.active_incident_count}</strong></div>
        </div>
      </article>
    `;
  });
  statusGrid.innerHTML = cards.join("");
}

function renderComponentGrid() {
  const components = getComponentsForSelectedStore();
  entityStatusTitle.textContent = `Components - ${state.selectedStoreId}`;
  entityStatusHint.textContent = "Select a component to view active alerts and acknowledge as needed.";
  entityBackBtn.classList.remove("hidden");

  if (!components.length) {
    statusGrid.innerHTML = "<div class=\"meta\">No components found for this store.</div>";
    return;
  }

  const cards = components.map((status) => {
    const storeId = escapeHtml(status.store_id);
    const component = escapeHtml(status.component);
    const statusColor = escapeHtml(status.status_color);
    const label = escapeHtml(statusLabel(status.status_color));
    const lastChangedAt = escapeHtml(new Date(status.last_changed_at).toLocaleString());
    const lastMessage = escapeHtml(status.last_message || "No incidents yet");
    const disabledLabel = status.disabled ? " | disabled" : "";

    return `
      <article
        class="tile status status-button ${statusColor} clickable"
        data-store-id="${storeId}"
        data-component="${component}"
        tabindex="0"
        role="button"
        aria-label="Open active alerts for ${storeId} ${component}"
      >
        <div class="eyebrow">Component</div>
        <div class="title">${component}</div>
        <div class="status-line">
          <span class="status-pill">${label}</span>
          <span class="meta">active: ${status.active_incident_count}${disabledLabel}</span>
        </div>
        <div class="meta">${lastChangedAt}</div>
        <div>${lastMessage}</div>
      </article>
    `;
  });

  statusGrid.innerHTML = cards.join("");
}

function renderStatusGrid() {
  if (state.selectedStoreId) {
    renderComponentGrid();
    return;
  }
  renderStoreGrid();
}

function renderIncidentList() {
  const visible = state.incidents
    .filter((event) => !state.acks.has(event.event_id))
    .sort(compareIncidentsByNewest);
  const rows = visible.slice(0, 150).map((event) => `
    <li class="incident-item" data-event-id="${event.event_id}">
      <strong>[${escapeHtml(event.severity)}]</strong> ${escapeHtml(event.store_id)}/${escapeHtml(event.component)} ${escapeHtml(event.event_type)}<br />
      ${escapeHtml(event.message)}<br />
      <small>${escapeHtml(new Date(event.happened_at).toLocaleString())} | ${escapeHtml(event.source)}</small><br />
      <button class="ack-btn" data-ack-event="${event.event_id}">Acknowledge</button>
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

  state.incidents = (payload.recent_events || []).slice();
  sortIncidentsNewestFirst();
  for (const ack of payload.active_acks || []) {
    state.acks.set(ack.event_id, ack);
  }
  renderAll();
}

function applyRealtimeUpdate(payload) {
  if (!payload?.kind) return;

  if (payload.kind === "ack_update" && payload.ack) {
    state.acks.set(payload.ack.event_id, payload.ack);
    renderAll();
    return;
  }

  if (payload.kind === "ack_expired" && payload.event_id) {
    state.acks.delete(payload.event_id);
    renderAll();
    return;
  }

  if (payload.kind === "status_timeout" && payload.status) {
    const key = `${payload.status.store_id}:${payload.status.component}`;
    state.statuses.set(key, payload.status);
    renderAll();
    return;
  }

  if (!payload?.status || !payload?.event) return;

  const key = `${payload.status.store_id}:${payload.status.component}`;
  state.statuses.set(key, payload.status);
  state.incidents.unshift(payload.event);
  sortIncidentsNewestFirst();
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
    if (state.pingTimerId) {
      clearInterval(state.pingTimerId);
    }
    state.pingTimerId = setInterval(() => {
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

function toUtcIso(value) {
  if (!value) return null;
  const local = new Date(value);
  return local.toISOString();
}

function openAckModal(eventId) {
  const incident = state.incidents.find((item) => item.event_id === eventId);
  state.pendingAckEventId = eventId;
  const summary = incident
    ? `${incident.store_id}/${incident.component} ${incident.event_type} ${incident.severity}`
    : eventId;
  document.getElementById("ackSummary").textContent = summary;

  const defaultExpiry = new Date(Date.now() + 30 * 60000);
  const localIso = new Date(defaultExpiry.getTime() - defaultExpiry.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
  document.getElementById("ackModalExpires").value = localIso;
  ackModal.showModal();
}

async function submitAckModal() {
  if (!state.pendingAckEventId) return;
  const payload = {
    event_id: state.pendingAckEventId,
    ack_message: document.getElementById("ackModalMessage").value.trim(),
    ack_by: "operator-console",
    expires_at: toUtcIso(document.getElementById("ackModalExpires").value),
  };

  const response = await fetch(`${API_BASE}/api/v1/acks`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Monitor-Key": "dev-monitor-key",
    },
    body: JSON.stringify(payload),
  });

  if (response.ok) {
    const ack = await response.json();
    state.acks.set(ack.event_id, ack);
    renderAll();
  }
  ackModal.close();
}

async function openEntityAlertsModal(storeId, component) {
  state.entityAlertsContext = { storeId, component };
  entityAlertsSummary.textContent = `${storeId} / ${component}`;
  entityAlertsList.innerHTML = "<li class=\"incident-item\">Loading active alerts...</li>";
  if (!entityAlertsModal.open) {
    entityAlertsModal.showModal();
  }

  try {
    const query = new URLSearchParams({ store_id: storeId, component });
    const response = await fetch(`${API_BASE}/api/v1/active-alerts?${query.toString()}`);
    if (!response.ok) throw new Error("Failed to load active alerts");

    const alerts = await response.json();
    if (!alerts.length) {
      entityAlertsList.innerHTML = "<li class=\"incident-item\">No active alerts for this entity.</li>";
      return;
    }

    const rows = alerts.map((event) => {
      const severity = escapeHtml(event.severity);
      const eventType = escapeHtml(event.event_type);
      const message = escapeHtml(event.message);
      const happenedAt = escapeHtml(new Date(event.happened_at).toLocaleString());
      const source = escapeHtml(event.source);
      const eventId = escapeHtml(event.event_id);
      const acked = state.acks.has(event.event_id) ? " | acknowledged" : "";
      const ackButton = state.acks.has(event.event_id)
        ? ""
        : `<button class=\"ack-btn\" data-ack-event=\"${eventId}\">Acknowledge</button>`;
      return `
        <li class="incident-item">
          <strong>[${severity}]</strong> ${eventType}${acked}<br />
          ${message}<br />
          <small>${happenedAt} | ${source} | ${eventId}</small><br />
          ${ackButton}
        </li>
      `;
    });
    entityAlertsList.innerHTML = rows.join("");
  } catch (error) {
    console.error(error);
    entityAlertsList.innerHTML = "<li class=\"incident-item\">Unable to load active alerts.</li>";
  }
}

async function refreshEntityAlertsModalIfOpen() {
  if (!entityAlertsModal.open || !state.entityAlertsContext) return;
  const { storeId, component } = state.entityAlertsContext;
  await openEntityAlertsModal(storeId, component);
}

function wireEntityStatusActions() {
  const openFromTile = (tile) => {
    const storeId = tile.getAttribute("data-store-id");
    const component = tile.getAttribute("data-component");
    if (!storeId) return;
    if (!component) {
      state.selectedStoreId = storeId;
      renderStatusGrid();
      return;
    }
    openEntityAlertsModal(storeId, component);
  };

  statusGrid.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const tile = target.closest(".tile.status.clickable");
    if (!(tile instanceof HTMLElement)) return;
    openFromTile(tile);
  });

  statusGrid.addEventListener("keydown", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const tile = target.closest(".tile.status.clickable");
    if (!(tile instanceof HTMLElement)) return;
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    openFromTile(tile);
  });

  document.getElementById("entityAlertsCloseBtn").addEventListener("click", () => {
    state.entityAlertsContext = null;
    entityAlertsModal.close();
  });

  entityAlertsModal.addEventListener("close", () => {
    state.entityAlertsContext = null;
  });

  entityBackBtn.addEventListener("click", () => {
    state.selectedStoreId = null;
    renderStatusGrid();
  });
}

function wireAckActions() {
  const onAckClick = (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const eventId = target.getAttribute("data-ack-event");
    if (!eventId) return;
    openAckModal(eventId);
  };

  incidentList.addEventListener("click", onAckClick);
  entityAlertsList.addEventListener("click", onAckClick);

  document.getElementById("ackForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    await submitAckModal();
    await refreshEntityAlertsModalIfOpen();
  });
  document.getElementById("ackCancelBtn").addEventListener("click", () => ackModal.close());
}

async function start() {
  try {
    await loadBootstrap();
  } catch (error) {
    console.error(error);
  }
  wireAckActions();
  wireEntityStatusActions();
  connectWebSocket();
}

start();

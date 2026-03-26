import { ensureMonitorApiKey, getMissingMonitorApiKeyMessage } from "./monitor-auth.js";

const pageUrl = new URL(window.location.href);
const apiUrl = new URL(pageUrl.origin);
apiUrl.protocol = pageUrl.protocol === "https:" ? "https:" : "http:";
apiUrl.port = "8000";

const wsUrl = new URL(apiUrl.origin);
wsUrl.protocol = pageUrl.protocol === "https:" ? "wss:" : "ws:";
wsUrl.pathname = "/ws/updates";

const API_BASE = window.MONITOR_API_BASE || apiUrl.origin;
const WS_BASE = window.MONITOR_WS_BASE || wsUrl.toString().replace(/\/$/, "");

const state = {
  statuses: new Map(),
  incidents: [],
  acks: new Map(),
  entityAlertsByEventId: new Map(),
  socket: null,
  reconnectAttempt: 0,
  pendingAckEventId: null,
  pendingResolveEventIds: new Set(),
  selectedStoreId: null,
  entityAlertsContext: null,
  pingTimerId: null,
  entityEventHistoryLimit: 1000,
  entityEventHistoryLimitOptions: [250, 500, 1000, 2000],
};

const FALLBACK_ENTITY_EVENT_HISTORY_LIMIT = 1000;
const FALLBACK_ENTITY_EVENT_HISTORY_LIMIT_OPTIONS = [250, 500, 1000, 2000];

const FILTER_ALERT_STORES = document.body.dataset.alertsFilter === "true";

const statusGrid = document.getElementById("statusGrid");
const incidentList = document.getElementById("incidentList");
const connectionBadge = document.getElementById("connectionBadge");
const ackModal = document.getElementById("ackModal");
const entityStatusTitle = document.getElementById("entityStatusTitle");
const entityStatusHint = document.getElementById("entityStatusHint");
const entityBackBtn = document.getElementById("entityBackBtn");
let entityAlertsModal = null;
let entityAlertsSummary = null;
let entityAlertsList = null;
let entityEventsLog = null;
let entityEventsLimitSelect = null;
const summaryStatusModal = document.getElementById("summaryStatusModal");
const summaryStatusTitle = document.getElementById("summaryStatusTitle");
const summaryStatusHint = document.getElementById("summaryStatusHint");
const summaryStatusBody = document.getElementById("summaryStatusBody");


function ensureEntityAlertsModal() {
  const existing = document.getElementById("entityAlertsModal");
  if (!existing) {
    document.body.insertAdjacentHTML("beforeend", `
      <dialog id="entityAlertsModal">
        <form method="dialog" id="entityAlertsForm">
          <h3>Active Alerts</h3>
          <p id="entityAlertsSummary" class="meta"></p>
          <div class="entity-alerts-grid">
            <section class="entity-alerts-panel currently-active-panel">
              <h4>Currently Active</h4>
              <ul id="entityAlertsList" class="incident-list compact active-alerts-static-list"></ul>
            </section>
            <section class="entity-alerts-panel events-log-panel">
              <div class="events-log-header-row">
                <h4>Last 24 Hours Events</h4>
                <label class="events-limit-control" for="entityEventsLimitSelect">
                  Rows
                  <select id="entityEventsLimitSelect" aria-label="Event history row limit"></select>
                </label>
              </div>
              <p class="meta">All event types for this component, newest first.</p>
              <div class="log-box" role="region" aria-label="Last 24 hours events log">
                <div id="entityEventsLog" class="events-history-list">Loading events...</div>
              </div>
            </section>
          </div>
          <div class="btn-row">
            <button type="button" id="entityAlertsCloseBtn">Close</button>
          </div>
        </form>
      </dialog>
    `);
  }

  entityAlertsModal = document.getElementById("entityAlertsModal");
  entityAlertsSummary = document.getElementById("entityAlertsSummary");
  entityAlertsList = document.getElementById("entityAlertsList");
  entityEventsLog = document.getElementById("entityEventsLog");
  entityEventsLimitSelect = document.getElementById("entityEventsLimitSelect");
  renderEntityHistoryLimitOptions();
}

function sanitizeHistoryLimitOptions(options) {
  if (!Array.isArray(options)) return FALLBACK_ENTITY_EVENT_HISTORY_LIMIT_OPTIONS.slice();
  const values = options
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value) && value >= 50 && value <= 5000)
    .map((value) => Math.floor(value));
  const uniqueSorted = [...new Set(values)].sort((a, b) => a - b);
  return uniqueSorted.length ? uniqueSorted : FALLBACK_ENTITY_EVENT_HISTORY_LIMIT_OPTIONS.slice();
}

function applyRuntimeConfig(config) {
  const options = sanitizeHistoryLimitOptions(config?.entity_history_limit_options);
  state.entityEventHistoryLimitOptions = options;

  const preferred = Number(config?.entity_history_default_limit);
  if (Number.isFinite(preferred) && options.includes(preferred)) {
    state.entityEventHistoryLimit = preferred;
  } else if (!options.includes(state.entityEventHistoryLimit)) {
    state.entityEventHistoryLimit = options[0] || FALLBACK_ENTITY_EVENT_HISTORY_LIMIT;
  }

  renderEntityHistoryLimitOptions();
}

function renderEntityHistoryLimitOptions() {
  if (!entityEventsLimitSelect) return;
  const options = state.entityEventHistoryLimitOptions.length
    ? state.entityEventHistoryLimitOptions
    : FALLBACK_ENTITY_EVENT_HISTORY_LIMIT_OPTIONS;

  entityEventsLimitSelect.innerHTML = options
    .map((value) => `<option value="${value}">${value}</option>`)
    .join("");
  entityEventsLimitSelect.value = String(state.entityEventHistoryLimit);
}

function truncateText(value, maxLength) {
  const text = String(value || "");
  if (text.length <= maxLength) return text;
  return `${text.slice(0, Math.max(0, maxLength - 1))}…`;
}

function truncateMiddle(value, headLength, tailLength) {
  const text = String(value || "");
  if (text.length <= headLength + tailLength + 1) return text;
  return `${text.slice(0, headLength)}…${text.slice(-tailLength)}`;
}

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

  const chips = document.querySelectorAll(".summary .chip-button[data-status-color]");
  for (const chip of chips) {
    const color = chip.getAttribute("data-status-color");
    if (!color || counts[color] === undefined) continue;
    chip.setAttribute("aria-label", `Show ${statusLabel(color)} entities (${counts[color]})`);
  }
}

function groupedStatusesForColor(statusColor) {
  const filtered = Array.from(state.statuses.values())
    .filter((status) => status.status_color === statusColor)
    .sort((a, b) => {
      const storeDiff = a.store_id.localeCompare(b.store_id);
      if (storeDiff !== 0) return storeDiff;
      return a.component.localeCompare(b.component);
    });

  const grouped = new Map();
  for (const row of filtered) {
    const list = grouped.get(row.store_id) || [];
    list.push(row);
    grouped.set(row.store_id, list);
  }
  return grouped;
}

function openSummaryStatusModal(statusColor) {
  if (!summaryStatusModal || !summaryStatusTitle || !summaryStatusHint || !summaryStatusBody) return;

  const modalColorClasses = [
    "status-modal-green",
    "status-modal-yellow",
    "status-modal-red",
    "status-modal-purple",
    "status-modal-white",
  ];
  summaryStatusModal.classList.remove(...modalColorClasses);
  summaryStatusModal.classList.add(`status-modal-${statusColor}`);

  const grouped = groupedStatusesForColor(statusColor);
  const colorLabel = statusLabel(statusColor);
  summaryStatusTitle.textContent = `${colorLabel} Entities`;

  const total = Array.from(grouped.values()).reduce((sum, list) => sum + list.length, 0);
  summaryStatusHint.textContent = `${total} store/component combinations in ${colorLabel}.`;

  if (!total) {
    summaryStatusBody.innerHTML = `<div class="meta">No store/component combinations are currently ${escapeHtml(colorLabel)}.</div>`;
  } else {
    const groups = Array.from(grouped.entries()).map(([storeId, entries]) => {
      const items = entries.map((row) => {
        const component = escapeHtml(row.component);
        const message = escapeHtml(row.last_message || "No message");
        const changedAt = escapeHtml(new Date(row.last_changed_at).toLocaleString());
        const activeCount = Number(row.active_incident_count || 0);
        return `
          <li class="summary-status-item">
            <div><strong>${component}</strong> <span class="meta">active: ${activeCount}</span></div>
            <div class="meta">${changedAt}</div>
            <div>${message}</div>
          </li>
        `;
      });

      return `
        <section class="summary-store-group">
          <div class="summary-store-header">
            <h4>${escapeHtml(storeId)}</h4>
            <button class="summary-open-store-btn" type="button" data-open-store="${escapeHtml(storeId)}">Open store</button>
          </div>
          <ul class="summary-status-list">
            ${items.join("")}
          </ul>
        </section>
      `;
    });

    summaryStatusBody.innerHTML = groups.join("");
  }

  if (!summaryStatusModal.open) {
    summaryStatusModal.showModal();
  }
}

function buildStoreSummaries() {
  const ackCountByStore = new Map();
  for (const ack of state.acks.values()) {
    const storeId = String(ack.store_id || "");
    if (!storeId) continue;
    ackCountByStore.set(storeId, (ackCountByStore.get(storeId) || 0) + 1);
  }

  const grouped = new Map();
  for (const status of state.statuses.values()) {
    const summary = grouped.get(status.store_id) || {
      store_id: status.store_id,
      status_color: "white",
      active_incident_count: 0,
      ack_count: 0,
      component_count: 0,
    };

    if (statusRank(status.status_color) > statusRank(summary.status_color)) {
      summary.status_color = status.status_color;
    }
    summary.active_incident_count += status.active_incident_count;
    summary.component_count += 1;
    grouped.set(status.store_id, summary);
  }

  for (const summary of grouped.values()) {
    const ackCount = ackCountByStore.get(summary.store_id) || 0;
    summary.ack_count = ackCount;
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
  let stores = buildStoreSummaries();
  entityStatusTitle.textContent = "Stores";
  entityStatusHint.textContent = "Select a store to view component health.";
  entityBackBtn.classList.add("hidden");

  if (FILTER_ALERT_STORES) {
    stores = stores.filter(
      (s) => s.status_color !== "green" && s.status_color !== "white"
    );
  } else {
    stores.sort((a, b) => compareStoreIdsByNumericSuffix(a.store_id, b.store_id));
  }

  if (!stores.length) {
    const msg = FILTER_ALERT_STORES
      ? "No active alerts — all stores are healthy."
      : "No stores are reporting yet.";
    statusGrid.innerHTML = `<div class="meta">${msg}</div>`;
    return;
  }

  const cards = stores.map((store) => {
    const storeId = escapeHtml(store.store_id);
    const statusColor = escapeHtml(store.status_color);
    const label = escapeHtml(statusLabel(store.status_color));
    const ackMetric = store.ack_count > 0
      ? `<div class="metric"><span>Acks</span><strong>${store.ack_count}</strong></div>`
      : "";
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
          ${ackMetric}
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
    .filter((event) => !state.acks.has(event.event_id));
  const rows = visible.slice(0, 150).map((event) => {
    const severityClass = `severity-${escapeHtml(event.severity)}`;
    const hasMeta = event.metadata && Object.keys(event.metadata).length > 0;
    const metaSection = hasMeta
      ? `<div class="metadata-expand">
          <button class="metadata-toggle-btn" type="button" aria-expanded="false">Metadata</button>
          <pre class="metadata-json" hidden>${escapeHtml(JSON.stringify(event.metadata, null, 2))}</pre>
        </div>`
      : "";

    return `
      <li class="incident-item ${severityClass}" data-event-id="${event.event_id}">
        <strong>[${escapeHtml(event.severity)}]</strong> ${escapeHtml(event.store_id)}/${escapeHtml(event.component)} ${escapeHtml(event.event_type)}<br />
        ${escapeHtml(event.message)}<br />
        <small>${escapeHtml(new Date(event.happened_at).toLocaleString())} | ${escapeHtml(event.source)}</small><br />
        ${metaSection}
        <button class="ack-btn" data-ack-event="${event.event_id}">Acknowledge</button>
      </li>
    `;
  });
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

  applyRuntimeConfig(payload.config);

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

function generateOkEventId() {
  if (window.crypto?.randomUUID) {
    return `evt-ui-ok-${window.crypto.randomUUID().slice(0, 8)}`;
  }
  const random = Math.random().toString(36).slice(2, 10);
  return `evt-ui-ok-${Date.now()}-${random}`;
}

function formatLogTimestamp(value) {
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return "-";
  const month = String(dt.getMonth() + 1).padStart(2, "0");
  const day = String(dt.getDate()).padStart(2, "0");
  const hours = String(dt.getHours()).padStart(2, "0");
  const minutes = String(dt.getMinutes()).padStart(2, "0");
  const seconds = String(dt.getSeconds()).padStart(2, "0");
  return `${month}/${day} ${hours}:${minutes}:${seconds}`;
}

function renderEntityEventsLog(historyEvents) {
  if (!entityEventsLog) return;
  if (!historyEvents.length) {
    entityEventsLog.innerHTML = "<div class=\"meta\">(no events for this component in the last 24 hours)</div>";
    return;
  }

  const rows = historyEvents.map((event) => {
    const hasMeta = event.metadata && Object.keys(event.metadata).length > 0;
    const metaSection = hasMeta
      ? `<div class="metadata-expand">
          <button class="metadata-toggle-btn" type="button" aria-expanded="false">Metadata</button>
          <pre class="metadata-json" hidden>${escapeHtml(JSON.stringify(event.metadata, null, 2))}</pre>
        </div>`
      : "";

    const severity = escapeHtml(String(event.severity || "-").toLowerCase());
    const eventType = escapeHtml(String(event.event_type || "-").toUpperCase());
    const stateLabel = event.active ? "active" : "closed";
    const timestamp = escapeHtml(formatLogTimestamp(event.happened_at));
    const source = escapeHtml(event.source || "-");
    const eventId = escapeHtml(event.event_id || "-");
    const message = escapeHtml(event.message || "");

    return `
      <article class="events-history-item severity-${severity}">
        <div class="events-history-header">
          <div class="events-history-badges">
            <span class="events-history-chip severity severity-${severity}">${severity}</span>
            <span class="events-history-chip type">${eventType}</span>
            <span class="events-history-chip state">${stateLabel}</span>
          </div>
          <span class="events-history-time">${timestamp}</span>
        </div>
        <div class="events-history-message">${message}</div>
        <div class="events-history-meta-row">
          <span class="events-history-source">${source}</span>
          <span class="events-history-event-id">${eventId}</span>
        </div>
        ${metaSection}
      </article>
    `;
  });

  entityEventsLog.innerHTML = rows.join("");
}

function currentEntityHistoryLimit() {
  const selected = Number(state.entityEventHistoryLimit);
  if (Number.isFinite(selected) && selected > 0) {
    return selected;
  }
  return FALLBACK_ENTITY_EVENT_HISTORY_LIMIT;
}

async function loadEntityEventsHistory(storeId, component) {
  if (entityEventsLog) {
    entityEventsLog.textContent = "Loading events...";
  }

  const query = new URLSearchParams({
    store_id: storeId,
    component,
    hours: "24",
    limit: String(currentEntityHistoryLimit()),
  });

  const response = await fetch(`${API_BASE}/api/v1/entity-events?${query.toString()}`);
  if (!response.ok) {
    throw new Error(`Unable to load 24-hour event history (HTTP ${response.status}).`);
  }

  const historyEvents = await response.json();
  renderEntityEventsLog(historyEvents);
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
  try {
    const payload = {
      event_id: state.pendingAckEventId,
      ack_message: document.getElementById("ackModalMessage").value.trim(),
      ack_by: "operator-console",
      expires_at: toUtcIso(document.getElementById("ackModalExpires").value),
    };
    const apiKey = ensureMonitorApiKey({
      message: getMissingMonitorApiKeyMessage("acknowledge alerts"),
    });

    const response = await fetch(`${API_BASE}/api/v1/acks`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Monitor-Key": apiKey,
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const detail = (await response.text()).trim();
      throw new Error(detail || `Failed to acknowledge alert (HTTP ${response.status}).`);
    }

    const ack = await response.json();
    state.acks.set(ack.event_id, ack);
    renderAll();
    ackModal.close();
  } catch (error) {
    window.alert(error?.message || String(error));
  }
}

async function openEntityAlertsModal(storeId, component) {
  if (!entityAlertsModal || !entityAlertsSummary || !entityAlertsList) return;
  state.entityAlertsContext = { storeId, component };
  state.entityAlertsByEventId.clear();
  entityAlertsSummary.textContent = `${storeId} / ${component}`;
  entityAlertsList.innerHTML = "<li class=\"incident-item\">Loading active alerts...</li>";
  if (entityEventsLog) {
    entityEventsLog.textContent = "Loading events...";
  }
  if (entityEventsLimitSelect) {
    entityEventsLimitSelect.value = String(currentEntityHistoryLimit());
  }
  if (!entityAlertsModal.open) {
    entityAlertsModal.showModal();
  }

  const query = new URLSearchParams({ store_id: storeId, component });
  const [alertsResult, historyResult] = await Promise.allSettled([
    fetch(`${API_BASE}/api/v1/active-alerts?${query.toString()}`),
    loadEntityEventsHistory(storeId, component),
  ]);

  if (alertsResult.status === "fulfilled") {
    const response = alertsResult.value;
    if (response.ok) {
      const alerts = await response.json();
      for (const event of alerts) {
        state.entityAlertsByEventId.set(event.event_id, event);
      }
      if (!alerts.length) {
        entityAlertsList.innerHTML = "<li class=\"incident-item\">No active alerts for this entity.</li>";
      } else {
        const rows = alerts.map((event) => {
          const severity = escapeHtml(event.severity);
          const severityClass = `severity-${String(event.severity || "").toLowerCase()}`;
          const eventType = escapeHtml(event.event_type);
          const message = escapeHtml(truncateText(event.message, 90));
          const happenedAt = escapeHtml(new Date(event.happened_at).toLocaleString());
          const source = escapeHtml(truncateText(event.source, 20));
          const eventId = escapeHtml(event.event_id);
          const eventIdCompact = escapeHtml(truncateMiddle(event.event_id, 10, 8));
          const acked = state.acks.has(event.event_id) ? " | acknowledged" : "";
          const ackButton = state.acks.has(event.event_id)
            ? ""
            : `<button class=\"ack-btn\" data-ack-event=\"${eventId}\">Acknowledge</button>`;
          const resolving = state.pendingResolveEventIds.has(event.event_id);
          const resolveButton = `<button class=\"resolve-btn\" data-resolve-event=\"${eventId}\" ${resolving ? "disabled" : ""}>${resolving ? "Resolving..." : "Resolve"}</button>`;
          const hasMeta = event.metadata && Object.keys(event.metadata).length > 0;
          const metaSection = hasMeta
            ? `<div class="metadata-expand">
                <button class="metadata-toggle-btn" type="button" aria-expanded="false">Metadata</button>
                <pre class="metadata-json" hidden>${escapeHtml(JSON.stringify(event.metadata, null, 2))}</pre>
              </div>`
            : "";
          return `
            <li class="incident-item ${severityClass}">
              <strong>[${severity}]</strong> ${eventType}${acked}<br />
              ${message}<br />
              <small>${happenedAt} | ${source} | ${eventIdCompact}</small><br />
              ${metaSection}
              <div class="incident-actions">
                ${ackButton}
                ${resolveButton}
              </div>
            </li>
          `;
        });

        entityAlertsList.innerHTML = rows.join("");
      }
    } else {
      entityAlertsList.innerHTML = `<li class=\"incident-item\">Unable to load active alerts (HTTP ${response.status}).</li>`;
    }
  } else {
    console.error(alertsResult.reason);
    entityAlertsList.innerHTML = "<li class=\"incident-item\">Unable to load active alerts.</li>";
  }

  if (historyResult.status !== "fulfilled") {
    console.error(historyResult.reason);
    if (entityEventsLog) {
      entityEventsLog.textContent = historyResult.reason?.message || "Unable to load 24-hour event history.";
    }
  }
}

async function refreshEntityAlertsModalIfOpen() {
  if (!entityAlertsModal || !entityAlertsModal.open || !state.entityAlertsContext) return;
  const { storeId, component } = state.entityAlertsContext;
  await openEntityAlertsModal(storeId, component);
}

async function submitResolveEvent(eventId) {
  const event = state.entityAlertsByEventId.get(eventId)
    || state.incidents.find((item) => item.event_id === eventId);
  if (!event || state.pendingResolveEventIds.has(eventId)) return;

  state.pendingResolveEventIds.add(eventId);

  try {
    const apiKey = ensureMonitorApiKey({
      message: getMissingMonitorApiKeyMessage("resolve alerts"),
    });
    const payload = {
      event_id: generateOkEventId(),
      dedup_key: event.dedup_key,
      store_id: event.store_id,
      component: event.component,
      event_type: "ok",
      severity: "info",
      message: "Resolved by operator from UI",
      source: event.source || "operator-console",
      metadata: {
        resolved_event_id: event.event_id,
        resolved_by: "operator-console",
      },
    };

    const response = await fetch(`${API_BASE}/api/v1/events`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Monitor-Key": apiKey,
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const detail = (await response.text()).trim();
      throw new Error(detail || `Failed to resolve alert ${eventId} (HTTP ${response.status}).`);
    }
  } catch (error) {
    console.error(error);
    window.alert(error?.message || String(error));
  } finally {
    state.pendingResolveEventIds.delete(eventId);
    await refreshEntityAlertsModalIfOpen();
  }
}

function wireEntityStatusActions() {
  if (!entityAlertsModal) return;
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

  const closeButton = document.getElementById("entityAlertsCloseBtn");
  if (closeButton) {
    closeButton.addEventListener("click", () => {
      state.entityAlertsContext = null;
      entityAlertsModal.close();
    });
  }

  entityAlertsModal.addEventListener("close", () => {
    state.entityAlertsContext = null;
  });

  entityBackBtn.addEventListener("click", () => {
    state.selectedStoreId = null;
    renderStatusGrid();
  });

  if (entityEventsLimitSelect) {
    entityEventsLimitSelect.addEventListener("change", async () => {
      const selected = Number(entityEventsLimitSelect.value);
      if (state.entityEventHistoryLimitOptions.includes(selected)) {
        state.entityEventHistoryLimit = selected;
      }
      if (!entityAlertsModal.open || !state.entityAlertsContext) return;
      const { storeId, component } = state.entityAlertsContext;
      try {
        await loadEntityEventsHistory(storeId, component);
      } catch (error) {
        console.error(error);
        if (entityEventsLog) {
          entityEventsLog.textContent = error?.message || "Unable to load 24-hour event history.";
        }
      }
    });
  }
}

function wireAckActions() {
  if (!entityAlertsList) return;
  const onMetadataToggleClick = (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const btn = target.closest(".metadata-toggle-btn");
    if (!(btn instanceof HTMLButtonElement)) return;
    const pre = btn.nextElementSibling;
    if (!pre) return;
    const expanded = btn.getAttribute("aria-expanded") === "true";
    btn.setAttribute("aria-expanded", String(!expanded));
    pre.hidden = expanded;
  };

  const onAckClick = (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const ackButton = target.closest("[data-ack-event]");
    if (!(ackButton instanceof HTMLElement)) return;
    const eventId = ackButton.getAttribute("data-ack-event");
    if (!eventId) return;
    openAckModal(eventId);
  };

  const onResolveClick = async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const resolveButton = target.closest("[data-resolve-event]");
    if (!(resolveButton instanceof HTMLButtonElement)) return;
    const eventId = resolveButton.getAttribute("data-resolve-event");
    if (!eventId) return;
    await submitResolveEvent(eventId);
  };

  incidentList.addEventListener("click", onAckClick);
  incidentList.addEventListener("click", onMetadataToggleClick);
  entityAlertsList.addEventListener("click", onMetadataToggleClick);
  if (entityEventsLog) {
    entityEventsLog.addEventListener("click", onMetadataToggleClick);
  }
  entityAlertsList.addEventListener("click", onAckClick);
  entityAlertsList.addEventListener("click", onResolveClick);

  document.getElementById("ackForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    await submitAckModal();
    await refreshEntityAlertsModalIfOpen();
  });
  document.getElementById("ackCancelBtn").addEventListener("click", () => ackModal.close());
}

function wireSummaryActions() {
  const chips = document.querySelectorAll(".summary .chip-button[data-status-color]");
  for (const chip of chips) {
    chip.addEventListener("click", () => {
      const statusColor = chip.getAttribute("data-status-color");
      if (!statusColor) return;
      openSummaryStatusModal(statusColor);
    });
  }

  const closeBtn = document.getElementById("summaryStatusCloseBtn");
  if (closeBtn && summaryStatusModal) {
    closeBtn.addEventListener("click", () => summaryStatusModal.close());
  }

  if (summaryStatusBody && summaryStatusModal) {
    summaryStatusBody.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      const openStoreBtn = target.closest("[data-open-store]");
      if (!(openStoreBtn instanceof HTMLElement)) return;

      const storeId = openStoreBtn.getAttribute("data-open-store");
      if (!storeId) return;
      state.selectedStoreId = storeId;
      summaryStatusModal.close();
      renderStatusGrid();
    });
  }
}

async function start() {
  ensureEntityAlertsModal();
  try {
    await loadBootstrap();
  } catch (error) {
    console.error(error);
  }
  wireAckActions();
  wireEntityStatusActions();
  wireSummaryActions();
  connectWebSocket();
}

start();

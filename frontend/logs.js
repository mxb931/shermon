const pageUrl = new URL(window.location.href);
const apiUrl = new URL(pageUrl.origin);
apiUrl.protocol = pageUrl.protocol === "https:" ? "https:" : "http:";
apiUrl.port = "8000";

const API_BASE = window.MONITOR_API_BASE || apiUrl.origin;

const form = document.getElementById("logsFilterForm");
const fileSelect = document.getElementById("logFile");
const sinceInput = document.getElementById("logsSince");
const untilInput = document.getElementById("logsUntil");
const severityInput = document.getElementById("logsSeverity");
const messageTypeInput = document.getElementById("logsMessageType");
const sourceInput = document.getElementById("logsSource");
const stateInput = document.getElementById("logsState");
const eventIdInput = document.getElementById("logsEventId");
const clientIpInput = document.getElementById("logsClientIp");
const queryInput = document.getElementById("logsQuery");
const limitInput = document.getElementById("logsLimit");
const liveViewInput = document.getElementById("logsLiveView");
const resetBtn = document.getElementById("logsResetBtn");
const prevBtn = document.getElementById("logsPrevBtn");
const nextBtn = document.getElementById("logsNextBtn");
const output = document.getElementById("logsOutput");
const summary = document.getElementById("logsSummary");

let offset = 0;
let lastTotal = 0;
let liveTimerId = null;
const LIVE_REFRESH_MS = 2000;
const FILTER_VALUES_REFRESH_MS = 30000;
let lastFilterValuesRefreshAt = 0;

function localIso(value) {
  if (!value) {
    return "";
  }
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) {
    return "";
  }
  return dt.toISOString();
}

function setSelectOptions(selectEl, values) {
  const previousValue = selectEl.value;
  selectEl.innerHTML = "";

  const anyOption = document.createElement("option");
  anyOption.value = "";
  anyOption.textContent = "Any";
  selectEl.appendChild(anyOption);

  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    selectEl.appendChild(option);
  }

  if (previousValue && values.includes(previousValue)) {
    selectEl.value = previousValue;
  }
}

function buildQuery() {
  if (liveViewInput.checked) {
    offset = 0;
  }
  const params = new URLSearchParams();
  const fileName = fileSelect.value.trim();
  if (fileName) {
    params.set("file_name", fileName);
  }
  const sinceIso = localIso(sinceInput.value);
  if (sinceIso) {
    params.set("since", sinceIso);
  }
  const untilIso = localIso(untilInput.value);
  if (untilIso) {
    params.set("until", untilIso);
  }
  if (severityInput.value) {
    params.set("severity", severityInput.value);
  }
  if (messageTypeInput.value.trim()) {
    params.set("message_type", messageTypeInput.value.trim());
  }
  if (sourceInput.value.trim()) {
    params.set("source", sourceInput.value.trim());
  }
  if (stateInput.value.trim()) {
    params.set("state", stateInput.value.trim());
  }
  if (eventIdInput.value.trim()) {
    params.set("event_id", eventIdInput.value.trim());
  }
  if (clientIpInput.value.trim()) {
    params.set("client_ip", clientIpInput.value.trim());
  }
  if (queryInput.value.trim()) {
    params.set("q", queryInput.value.trim());
  }
  params.set("limit", String(Math.min(500, Math.max(10, Number(limitInput.value) || 100))));
  params.set("offset", String(Math.max(0, offset)));
  return params;
}

function timestampFromRaw(rawLine) {
  const text = String(rawLine || "");
  const legacyMatch = text.match(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3,6})\b/);
  if (legacyMatch) {
    return legacyMatch[1];
  }

  const isoMatch = text.match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2}))\b/);
  if (isoMatch) {
    return isoMatch[1];
  }

  return null;
}

function rowTimestamp(row) {
  if (row.timestamp) {
    return row.timestamp;
  }
  return timestampFromRaw(row.raw) || "-";
}

function renderRows(payload) {
  const lines = payload.items.map((row) => {
    const ts = rowTimestamp(row);
    const sev = row.severity || "-";
    const msgType = row.message_type || "-";
    const source = row.source || "-";
    const state = row.state || "-";
    const eventId = row.event_id || "-";
    const ip = row.client_ip || "-";
    const msg = row.message || "";
    return `${ts} | ${sev} | ${msgType} | source=${source} | state=${state} | event_id=${eventId} | ip=${ip} | ${msg}`;
  });

  output.textContent = lines.length ? lines.join("\n") : "No logs matched the current filters.";
  const liveText = liveViewInput.checked ? ` Live: ON (${LIVE_REFRESH_MS / 1000}s refresh)` : " Live: OFF";
  summary.textContent = `Showing ${payload.items.length} of ${payload.total} rows (offset ${payload.offset}).${liveText}`;

  if (liveViewInput.checked) {
    prevBtn.disabled = true;
    nextBtn.disabled = true;
  } else {
    prevBtn.disabled = payload.offset <= 0;
    nextBtn.disabled = payload.offset + payload.limit >= payload.total;
  }
}

function stopLiveView() {
  if (liveTimerId !== null) {
    clearInterval(liveTimerId);
    liveTimerId = null;
  }
}

function startLiveView() {
  stopLiveView();
  if (!liveViewInput.checked) {
    return;
  }
  liveTimerId = window.setInterval(() => {
    loadLogs().catch((error) => {
      output.textContent = String(error);
    });
  }, LIVE_REFRESH_MS);
}

async function loadFiles() {
  const response = await fetch(`${API_BASE}/api/v1/log-files`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Could not load log files (HTTP ${response.status})`);
  }
  const files = await response.json();
  fileSelect.innerHTML = "";
  const anyOption = document.createElement("option");
  anyOption.value = "";
  anyOption.textContent = "Current Active Log";
  fileSelect.appendChild(anyOption);
  for (const file of files) {
    const option = document.createElement("option");
    option.value = file.name;
    option.textContent = `${file.name}${file.active ? " (active)" : ""}`;
    fileSelect.appendChild(option);
  }
}

async function loadFilterValues() {
  const response = await fetch(`${API_BASE}/api/v1/logs/filter-values`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Could not load log filter values (HTTP ${response.status})`);
  }
  const payload = await response.json();
  setSelectOptions(messageTypeInput, payload.message_types || []);
  setSelectOptions(sourceInput, payload.sources || []);
  setSelectOptions(stateInput, payload.states || []);
  lastFilterValuesRefreshAt = Date.now();
}

async function loadLogs() {
  if (Date.now() - lastFilterValuesRefreshAt >= FILTER_VALUES_REFRESH_MS) {
    await loadFilterValues();
  }
  const params = buildQuery();
  const response = await fetch(`${API_BASE}/api/v1/logs?${params.toString()}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Could not load logs (HTTP ${response.status})`);
  }
  const payload = await response.json();
  lastTotal = payload.total;
  renderRows(payload);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  offset = 0;
  try {
    await loadFilterValues();
    await loadLogs();
  } catch (error) {
    output.textContent = String(error);
  }
});

resetBtn.addEventListener("click", async () => {
  form.reset();
  limitInput.value = "100";
  offset = 0;
  stopLiveView();
  try {
    await loadFilterValues();
    await loadLogs();
  } catch (error) {
    output.textContent = String(error);
  }
});

prevBtn.addEventListener("click", async () => {
  const limit = Math.min(500, Math.max(10, Number(limitInput.value) || 100));
  offset = Math.max(0, offset - limit);
  try {
    await loadLogs();
  } catch (error) {
    output.textContent = String(error);
  }
});

nextBtn.addEventListener("click", async () => {
  const limit = Math.min(500, Math.max(10, Number(limitInput.value) || 100));
  if (offset + limit >= lastTotal) {
    return;
  }
  offset += limit;
  try {
    await loadLogs();
  } catch (error) {
    output.textContent = String(error);
  }
});

liveViewInput.addEventListener("change", async () => {
  offset = 0;
  if (liveViewInput.checked) {
    startLiveView();
  } else {
    stopLiveView();
  }
  try {
    await loadLogs();
  } catch (error) {
    output.textContent = String(error);
  }
});

(async () => {
  try {
    await loadFiles();
    await loadFilterValues();
    await loadLogs();
    startLiveView();
  } catch (error) {
    output.textContent = String(error);
  }
})();

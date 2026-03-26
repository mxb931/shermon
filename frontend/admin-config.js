const pageUrl = new URL(window.location.href);
const apiUrl = new URL(pageUrl.origin);
apiUrl.protocol = pageUrl.protocol === "https:" ? "https:" : "http:";
apiUrl.port = "8000";

const API_BASE = window.MONITOR_API_BASE || apiUrl.origin;

const DEFAULTS = {
  sweeper_interval_seconds: 60,
  entity_history_default_limit: 1000,
  entity_history_limit_options: [250, 500, 1000, 2000],
  log_max_mb: 50,
  log_backup_count: 20,
};

const form = document.getElementById("adminConfigForm");
const apiKeyInput = document.getElementById("adminApiKey");
const sweeperIntervalInput = document.getElementById("sweeperIntervalSeconds");
const defaultLimitInput = document.getElementById("entityHistoryDefaultLimit");
const optionsInput = document.getElementById("entityHistoryLimitOptions");
const logMaxMbInput = document.getElementById("logMaxMb");
const logBackupCountInput = document.getElementById("logBackupCount");
const reloadBtn = document.getElementById("adminConfigReloadBtn");
const resetBtn = document.getElementById("adminConfigResetBtn");
const result = document.getElementById("adminConfigResult");

function showResult(label, payload) {
  result.textContent = `${label}\n${JSON.stringify(payload, null, 2)}`;
}

function optionsFromInput(text) {
  const values = String(text || "")
    .split(",")
    .map((part) => Number(part.trim()))
    .filter((value) => Number.isFinite(value));
  return [...new Set(values.map((value) => Math.floor(value)))].sort((a, b) => a - b);
}

function setFormValues(payload) {
  sweeperIntervalInput.value = String(payload.sweeper_interval_seconds);
  defaultLimitInput.value = String(payload.entity_history_default_limit);
  optionsInput.value = payload.entity_history_limit_options.join(",");
  logMaxMbInput.value = String(payload.log_max_mb);
  logBackupCountInput.value = String(payload.log_backup_count);
}

async function loadConfig() {
  const response = await fetch(`${API_BASE}/api/v1/config`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load config (HTTP ${response.status})`);
  }
  const payload = await response.json();
  setFormValues(payload);
  showResult("Loaded config", payload);
}

async function saveConfig(config) {
  const response = await fetch(`${API_BASE}/api/v1/config`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      "X-Monitor-Key": apiKeyInput.value,
    },
    body: JSON.stringify(config),
  });

  let payload = {};
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }

  if (!response.ok) {
    throw new Error(payload?.detail ? JSON.stringify(payload.detail) : `Failed to save config (HTTP ${response.status})`);
  }

  setFormValues(payload);
  showResult("Saved config", payload);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    sweeper_interval_seconds: Number(sweeperIntervalInput.value),
    entity_history_default_limit: Number(defaultLimitInput.value),
    entity_history_limit_options: optionsFromInput(optionsInput.value),
    log_max_mb: Number(logMaxMbInput.value),
    log_backup_count: Number(logBackupCountInput.value),
  };

  try {
    await saveConfig(payload);
  } catch (error) {
    showResult("Save failed", { error: String(error) });
  }
});

reloadBtn.addEventListener("click", async () => {
  try {
    await loadConfig();
  } catch (error) {
    showResult("Reload failed", { error: String(error) });
  }
});

resetBtn.addEventListener("click", async () => {
  setFormValues(DEFAULTS);
  try {
    await saveConfig(DEFAULTS);
  } catch (error) {
    showResult("Reset failed", { error: String(error) });
  }
});

loadConfig().catch((error) => {
  showResult("Load failed", { error: String(error) });
});

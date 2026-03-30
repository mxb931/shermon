import { bindApiKeyInput, ensureMonitorApiKey } from "./monitor-auth.js";

const API_BASE = window.MONITOR_API_BASE || window.location.origin;

const apiKeyInput = document.getElementById("maintenanceApiKey");
const apiKeyMessage = document.getElementById("maintenanceApiKeyMessage");
const missingApiKeyMessage = "Enter an API key to perform maintenance actions.";

const retireForm = document.getElementById("retireForm");
const retireStoreIdInput = document.getElementById("retireStoreId");
const retireComponentInput = document.getElementById("retireComponent");
const retireValidationMessage = document.getElementById("retireValidationMessage");

const resultBox = document.getElementById("maintenanceResult");

const confirmDialog = document.getElementById("retireConfirmDialog");
const confirmMessage = document.getElementById("retireConfirmMessage");
const confirmInput = document.getElementById("retireConfirmInput");
const confirmError = document.getElementById("retireConfirmError");
const confirmOkBtn = document.getElementById("retireConfirmOkBtn");
const confirmCancelBtn = document.getElementById("retireConfirmCancelBtn");

bindApiKeyInput(apiKeyInput, apiKeyMessage, missingApiKeyMessage);

function showResult(label, payload) {
  resultBox.hidden = false;
  resultBox.textContent = `${label}\n${JSON.stringify(payload, null, 2)}`;
}

function apiHeaders() {
  const apiKey = ensureMonitorApiKey({
    inputEl: apiKeyInput,
    messageEl: apiKeyMessage,
    message: missingApiKeyMessage,
  });
  return {
    "Content-Type": "application/json",
    "X-Monitor-Key": apiKey,
  };
}

async function postAction(path, body) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: apiHeaders(),
    body: JSON.stringify(body),
  });

  let payload = {};
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }

  if (!response.ok) {
    throw new Error(payload?.detail ? JSON.stringify(payload.detail) : `Request failed (HTTP ${response.status})`);
  }
  return payload;
}

// Resolves when the user confirms (returns true) or cancels (returns false).
function showConfirmDialog(message) {
  return new Promise((resolve) => {
    confirmMessage.textContent = message;
    confirmInput.value = "";
    confirmError.hidden = true;
    confirmDialog.showModal();

    function cleanup() {
      confirmOkBtn.removeEventListener("click", onOk);
      confirmCancelBtn.removeEventListener("click", onCancel);
    }

    function onOk() {
      if (confirmInput.value.trim() !== "I understand") {
        confirmError.textContent = 'You must type exactly "I understand" to proceed.';
        confirmError.hidden = false;
        confirmInput.focus();
        return;
      }
      cleanup();
      confirmDialog.close();
      resolve(true);
    }

    function onCancel() {
      cleanup();
      confirmDialog.close();
      resolve(false);
    }

    confirmOkBtn.addEventListener("click", onOk);
    confirmCancelBtn.addEventListener("click", onCancel);
  });
}

function buildSternMessage(store_id, component) {
  if (store_id && component) {
    return (
      `You are about to retire the "${component}" component for store "${store_id}". ` +
      `This will immediately remove this entity from all monitoring views. ` +
      `Any active alerts for this component on this store will no longer be visible to operators. ` +
      `This action takes effect immediately. The entity will only reappear if a new event is received for it.`
    );
  }
  if (store_id) {
    return (
      `You are about to retire store "${store_id}" entirely. ` +
      `This will immediately hide EVERY component for this store from all monitoring views. ` +
      `Any active alerts for any component of this store will no longer be visible to operators. ` +
      `This action takes effect immediately. The store will only reappear if a new event is received for it.`
    );
  }
  // component only
  return (
    `You are about to retire the "${component}" component across EVERY store that currently reports it. ` +
    `This will immediately remove all instances of "${component}" from all monitoring views, ` +
    `regardless of which store they belong to. ` +
    `Any active alerts for this component on any store will no longer be visible to operators. ` +
    `This action takes effect immediately. Each instance will only reappear when a new event is received for it.`
  );
}

retireForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const store_id = retireStoreIdInput.value.trim();
  const component = retireComponentInput.value.trim();

  if (!store_id && !component) {
    retireValidationMessage.textContent = "Enter a Store ID, a Component, or both.";
    retireValidationMessage.hidden = false;
    return;
  }
  retireValidationMessage.hidden = true;

  const confirmed = await showConfirmDialog(buildSternMessage(store_id, component));
  if (!confirmed) return;

  try {
    let result;
    let label;

    if (store_id && component) {
      result = await postAction("/api/v1/maintenance/retire-component", { store_id, component });
      label = `Retired component: ${store_id} / ${component}`;
    } else if (store_id) {
      result = await postAction("/api/v1/maintenance/retire-store", { store_id });
      label = `Retired store: ${store_id}`;
    } else {
      result = await postAction("/api/v1/maintenance/retire-component-global", { component });
      label = `Retired component globally: ${component}`;
    }

    retireStoreIdInput.value = "";
    retireComponentInput.value = "";
    showResult(label, result);
  } catch (err) {
    showResult("Retire failed", { error: String(err) });
  }
});


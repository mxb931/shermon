const STORAGE_KEY = "monitor_api_key";
const FALLBACK_KEY = window.MONITOR_API_KEY || "";

function normalize(value) {
  return String(value || "").trim();
}

function setValidationState(inputEl, messageEl, message) {
  if (inputEl instanceof HTMLInputElement || inputEl instanceof HTMLSelectElement) {
    inputEl.setCustomValidity(message);
    inputEl.setAttribute("aria-invalid", message ? "true" : "false");
  }

  if (messageEl instanceof HTMLElement) {
    messageEl.textContent = message;
    messageEl.hidden = !message;
  }
}

export function getMissingMonitorApiKeyMessage(actionText = "complete this action") {
  return `No API key is configured. Enter one in Admin Config or Test Sender before trying to ${actionText}.`;
}

export function getMonitorApiKey() {
  try {
    const stored = normalize(window.localStorage.getItem(STORAGE_KEY));
    if (stored) return stored;
  } catch {
    // Ignore storage access errors and fall back to default.
  }
  return FALLBACK_KEY;
}

export function setMonitorApiKey(value) {
  const normalized = normalize(value);
  try {
    if (normalized) {
      window.localStorage.setItem(STORAGE_KEY, normalized);
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // Ignore storage write errors; normalized value is still returned.
  }
  return normalized || FALLBACK_KEY;
}

export function ensureMonitorApiKey({ inputEl = null, messageEl = null, message = getMissingMonitorApiKeyMessage() } = {}) {
  const apiKey = getMonitorApiKey();
  if (!apiKey) {
    setValidationState(inputEl, messageEl, message);
    if (inputEl instanceof HTMLElement) inputEl.focus();
    throw new Error(message);
  }

  setValidationState(inputEl, messageEl, "");
  return apiKey;
}

export function bindApiKeyInput(inputEl, messageEl = null, emptyMessage = "") {
  if (!(inputEl instanceof HTMLInputElement || inputEl instanceof HTMLSelectElement)) return;

  const applyCurrent = () => {
    const current = getMonitorApiKey();
    if (inputEl instanceof HTMLSelectElement) {
      inputEl.innerHTML = `<option value="${current}">${current}</option>`;
      inputEl.value = current;
      return;
    }
    inputEl.value = current;
    setValidationState(inputEl, messageEl, current ? "" : emptyMessage);
  };

  applyCurrent();

  inputEl.addEventListener("change", () => {
    const next = setMonitorApiKey(inputEl.value);
    if (inputEl instanceof HTMLSelectElement) {
      inputEl.innerHTML = `<option value="${next}">${next}</option>`;
      inputEl.value = next;
      return;
    }
    inputEl.value = next;
    setValidationState(inputEl, messageEl, next ? "" : emptyMessage);
  });

  if (inputEl instanceof HTMLInputElement) {
    inputEl.addEventListener("blur", () => {
      const next = setMonitorApiKey(inputEl.value);
      inputEl.value = next;
      setValidationState(inputEl, messageEl, next ? "" : emptyMessage);
    });
  }
}

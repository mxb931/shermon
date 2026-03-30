const defaultWsUrl = new URL("/ws/updates", window.location.origin);
defaultWsUrl.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
const WS_BASE = window.MONITOR_WS_BASE || defaultWsUrl.toString().replace(/\/$/, "");

const badge = document.getElementById("connectionBadge");

if (badge) {
  let reconnectAttempt = 0;
  let pingTimerId = null;

  function updateConnectionBadge(mode) {
    badge.className = `badge ${mode}`;
    badge.textContent = mode;
  }

  function reconnectDelay(attempt) {
    const raw = Math.min(1000 * (2 ** attempt), 15000);
    return raw + Math.floor(Math.random() * 400);
  }

  function connectWebSocket() {
    updateConnectionBadge("reconnecting");
    const ws = new WebSocket(WS_BASE);

    ws.onopen = () => {
      reconnectAttempt = 0;
      updateConnectionBadge("connected");
      ws.send("ping");
      if (pingTimerId) {
        clearInterval(pingTimerId);
      }
      pingTimerId = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send("ping");
      }, 15000);
    };

    ws.onclose = () => {
      if (pingTimerId) {
        clearInterval(pingTimerId);
        pingTimerId = null;
      }
      updateConnectionBadge("stale");
      const delay = reconnectDelay(reconnectAttempt);
      reconnectAttempt += 1;
      setTimeout(connectWebSocket, delay);
    };

    ws.onerror = () => ws.close();
  }

  connectWebSocket();
}
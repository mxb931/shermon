const WS_BASE = window.MONITOR_WS_BASE || "ws://localhost:8000/ws/updates";

const badge = document.getElementById("connectionBadge");

if (badge) {
  let reconnectAttempt = 0;

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
      setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send("ping");
      }, 15000);
    };

    ws.onclose = () => {
      updateConnectionBadge("stale");
      const delay = reconnectDelay(reconnectAttempt);
      reconnectAttempt += 1;
      setTimeout(connectWebSocket, delay);
    };

    ws.onerror = () => ws.close();
  }

  connectWebSocket();
}
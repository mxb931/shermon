"""
Smoke tests for the SherMon backend.
Run with: python3 tests/smoke_test.py
Server must be running on http://127.0.0.1:8000
"""

import json
import sys
import time
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8000"
KEY = "dev-monitor-key"
PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

results = []
RUN_ID = str(int(time.time()))


def request(method, path, payload=None, key=KEY):
    url = BASE + path
    data = json.dumps(payload).encode() if payload else None
    headers = {"Content-Type": "application/json", "X-Monitor-Key": key}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, {}


def check(label, condition, detail=""):
    if condition:
        print(f"  {PASS}  {label}")
        results.append(True)
    else:
        print(f"  {FAIL}  {label}  {detail}")
        results.append(False)


def event(event_id, dedup_key, store_id, component, event_type, severity, message):
    return {
        "event_id": event_id,
        "dedup_key": dedup_key,
        "store_id": store_id,
        "component": component,
        "event_type": event_type,
        "severity": severity,
        "message": message,
        "source": "smoke-test",
        "metadata": {},
    }


def ack_payload(event_id):
    return {
        "event_id": event_id,
        "ack_message": "Investigating",
        "ack_by": "smoke-test",
        "expires_at": "2099-01-01T00:00:00Z",
    }


print("\n--- Health ---")
status, body = request("GET", "/health")
check("health returns 200", status == 200)
check("status field is ok", body.get("status") == "ok")


print("\n--- Auth rejection ---")
status, _ = request(
    "POST",
    "/api/v1/events",
    event("auth-test", "AUTH", "s", "c", "problem", "critical", "test"),
    key="wrong-key",
)
check("bad API key returns 401", status == 401)


print("\n--- Expired event validation ---")
expired_event = event(
    f"evt-expired-{RUN_ID}",
    f"EXP_CHECK_{RUN_ID}",
    "store-104",
    "payments",
    "problem",
    "critical",
    "Expired event",
)
expired_event["expires_at"] = "2000-01-01T00:00:00Z"
status, _ = request("POST", "/api/v1/events", expired_event)
check("past expires_at returns 422", status == 422)


print("\n--- First problem event (critical) ---")
status, body = request(
    "POST",
    "/api/v1/events",
    event(f"evt-T01-{RUN_ID}", f"PAY_TIMEOUT_{RUN_ID}", "store-104", "payments", "problem", "critical", "Gateway timeout"),
)
check("accepted", body.get("accepted") is True, body)
check("not deduplicated", body.get("deduplicated") is False, body)
check("sequence assigned", isinstance(body.get("sequence"), int), body)
seq1 = body.get("sequence", 0)


print("\n--- Duplicate dedup_key (same active problem) ---")
status, body = request(
    "POST",
    "/api/v1/events",
    event(f"evt-T02-{RUN_ID}", f"PAY_TIMEOUT_{RUN_ID}", "store-104", "payments", "problem", "critical", "Still timing out"),
)
check("accepted", body.get("accepted") is True, body)
check("marked as deduplicated", body.get("deduplicated") is True, body)
check("sequence incremented", body.get("sequence", 0) > seq1, body)


print("\n--- Exact same event_id (idempotency) ---")
status, body = request(
    "POST",
    "/api/v1/events",
    event(f"evt-T01-{RUN_ID}", f"PAY_TIMEOUT_{RUN_ID}", "store-104", "payments", "problem", "critical", "Gateway timeout"),
)
check("accepted returns True (idempotent)", body.get("accepted") is True, body)
check("deduplicated True for exact replay", body.get("deduplicated") is True, body)


print("\n--- Warning on a different component ---")
e = event(f"evt-T03-{RUN_ID}", f"INV_LAG_{RUN_ID}", "store-104", "inventory", "problem", "warning", "Sync delayed")
status, body = request("POST", "/api/v1/events", e)
check("warning accepted", body.get("accepted") is True, body)
check("not deduplicated", body.get("deduplicated") is False, body)


print("\n--- Recovery for payments ---")
status, body = request(
    "POST",
    "/api/v1/events",
    event(f"evt-T04-{RUN_ID}", f"PAY_TIMEOUT_{RUN_ID}", "store-104", "payments", "recovery", "info", "Gateway recovered"),
)
check("recovery accepted", body.get("accepted") is True, body)


print("\n--- Bootstrap endpoint ---")
status, body = request("GET", "/api/v1/bootstrap")
check("returns 200", status == 200)
check("has statuses list", isinstance(body.get("statuses"), list), body)
check("has recent_events list", isinstance(body.get("recent_events"), list), body)
check("has latest_sequence", isinstance(body.get("latest_sequence"), int), body)

store_104_payments = next(
    (s for s in body.get("statuses", []) if s["store_id"] == "store-104" and s["component"] == "payments"),
    None,
)
check("payments entity present", store_104_payments is not None)
check(
    "payments status is green after recovery",
    store_104_payments and store_104_payments.get("status_color") == "green",
    store_104_payments,
)

store_104_inv = next(
    (s for s in body.get("statuses", []) if s["store_id"] == "store-104" and s["component"] == "inventory"),
    None,
)
check(
    "inventory status is yellow (unresolved warning)",
    store_104_inv and store_104_inv.get("status_color") == "yellow",
    store_104_inv,
)


print("\n--- Summary endpoint ---")
status, body = request("GET", "/api/v1/summary")
check("returns 200", status == 200)
check("has counts", "counts" in body, body)
counts = body.get("counts", {})
check("has green count", "green" in counts, counts)
check("has red count", "red" in counts, counts)
check("has yellow count", "yellow" in counts, counts)
check("has purple count", "purple" in counts, counts)
check("has white count", "white" in counts, counts)


print("\n--- Acknowledgement lifecycle ---")
status, body = request("POST", "/api/v1/acks", ack_payload(f"evt-T03-{RUN_ID}"))
check("ack create returns 200", status == 200, body)
check("ack create returns same event_id", body.get("event_id") == f"evt-T03-{RUN_ID}", body)

status, body = request("GET", "/api/v1/acks")
check("ack list returns 200", status == 200, body)
check("ack list contains new ack", any(a.get("event_id") == f"evt-T03-{RUN_ID}" for a in body), body)

status, body = request("DELETE", f"/api/v1/acks/evt-T03-{RUN_ID}")
check("ack delete returns 200", status == 200, body)
check("ack delete marks expired true", body.get("expired") is True, body)


passed = sum(results)
failed = len(results) - passed
print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed out of {len(results)} checks")
if failed:
    sys.exit(1)

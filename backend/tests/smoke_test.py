"""
Smoke tests for the SherMon backend.
Run with: python3 tests/smoke_test.py
Server must be running on http://127.0.0.1:8000
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

BASE = os.getenv("SMOKE_BASE", "http://127.0.0.1:8000")
KEY = "dev-monitor-key"
PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

results = []
RUN_ID = str(int(time.time()))


def request(method, path, payload=None, key=KEY):
    url = BASE + path
    data = json.dumps(payload).encode() if payload else None
    headers = {"Content-Type": "application/json"}
    if key is not None:
        headers["X-Monitor-Key"] = key
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


print("\n--- Runtime config API ---")
status, body = request("GET", "/api/v1/config")
check("config get returns 200", status == 200, body)
check("config has sweeper interval", isinstance(body.get("sweeper_interval_seconds"), int), body)
check("config has history default", isinstance(body.get("entity_history_default_limit"), int), body)
check("config has history options", isinstance(body.get("entity_history_limit_options"), list), body)
check("config has log max mb", isinstance(body.get("log_max_mb"), int), body)
check("config has log backup count", isinstance(body.get("log_backup_count"), int), body)

invalid_config = {
    "sweeper_interval_seconds": 30,
    "entity_history_default_limit": 750,
    "entity_history_limit_options": [250, 500, 1000],
    "log_max_mb": 50,
    "log_backup_count": 20,
}
status, _ = request("PUT", "/api/v1/config", invalid_config)
check("config put rejects default not in options", status == 422)

valid_config = {
    "sweeper_interval_seconds": 30,
    "entity_history_default_limit": 500,
    "entity_history_limit_options": [250, 500, 1000],
    "log_max_mb": 50,
    "log_backup_count": 20,
}
status, body = request("PUT", "/api/v1/config", valid_config)
check("config put returns 200", status == 200, body)
check("config put persists sweeper interval", body.get("sweeper_interval_seconds") == 30, body)
check("config put persists default history limit", body.get("entity_history_default_limit") == 500, body)
check("config put persists history options", body.get("entity_history_limit_options") == [250, 500, 1000], body)
check("config put persists log max mb", body.get("log_max_mb") == 50, body)
check("config put persists log backup count", body.get("log_backup_count") == 20, body)

status, body = request("GET", "/api/v1/config")
check("config get reflects updated values", status == 200 and body.get("entity_history_default_limit") == 500, body)

status, bootstrap_body = request("GET", "/api/v1/bootstrap")
check("bootstrap includes config payload", isinstance(bootstrap_body.get("config"), dict), bootstrap_body.get("config"))
check(
    "bootstrap config history options reflect update",
    bootstrap_body.get("config", {}).get("entity_history_limit_options") == [250, 500, 1000],
    bootstrap_body.get("config"),
)
check("bootstrap config includes log max mb", bootstrap_body.get("config", {}).get("log_max_mb") == 50, bootstrap_body.get("config"))
check("bootstrap config includes log backup count", bootstrap_body.get("config", {}).get("log_backup_count") == 20, bootstrap_body.get("config"))


print("\n--- Stale interval validation ---")
invalid_stale_interval = event(
    f"evt-stale-bad-{RUN_ID}",
    f"STALE_BAD_{RUN_ID}",
    "store-104",
    "payments",
    "problem",
    "critical",
    "Invalid stale interval",
)
invalid_stale_interval["stale_interval"] = "10s"
status, _ = request("POST", "/api/v1/events", invalid_stale_interval)
check("invalid stale_interval returns 422", status == 422)

valid_stale_interval = event(
    f"evt-stale-good-{RUN_ID}",
    f"STALE_GOOD_{RUN_ID}",
    "store-104",
    "network",
    "problem",
    "warning",
    "Valid stale interval",
)
valid_stale_interval["stale_interval"] = "2d5h10m"
status, body = request("POST", "/api/v1/events", valid_stale_interval)
check("valid stale_interval accepted", body.get("accepted") is True, body)

legacy_expected_field = event(
    f"evt-legacy-expected-{RUN_ID}",
    f"LEG_EXP_{RUN_ID}",
    "store-104",
    "network",
    "problem",
    "warning",
    "Legacy expected field",
)
legacy_expected_field["expected_green_interval_seconds"] = 120
status, _ = request("POST", "/api/v1/events", legacy_expected_field)
check("legacy expected_green_interval_seconds rejected", status == 422)

legacy_expires_field = event(
    f"evt-legacy-exp-{RUN_ID}",
    f"LEG_EXPIRES_{RUN_ID}",
    "store-104",
    "network",
    "problem",
    "warning",
    "Legacy expires field",
)
legacy_expires_field["expires_at"] = "2099-01-01T00:00:00Z"
status, _ = request("POST", "/api/v1/events", legacy_expires_field)
check("legacy event expires_at rejected", status == 422)


print("\n--- Event type and severity validation ---")
status, _ = request(
    "POST",
    "/api/v1/events",
    event(f"evt-inv-s1-{RUN_ID}", f"INV_SEV1_{RUN_ID}", "store-101", "network", "problem", "info", "Invalid combo"),
)
check("problem+info rejected", status == 422)

status, _ = request(
    "POST",
    "/api/v1/events",
    event(f"evt-inv-s2-{RUN_ID}", f"INV_SEV2_{RUN_ID}", "store-101", "network", "ok", "warning", "Invalid combo"),
)
check("ok+warning rejected", status == 422)

status, _ = request(
    "POST",
    "/api/v1/events",
    event(f"evt-inv-s3-{RUN_ID}", f"INV_SEV3_{RUN_ID}", "store-101", "network", "enable", "critical", "Invalid combo"),
)
check("enable+critical rejected", status == 422)

status, _ = request(
    "POST",
    "/api/v1/events",
    event(f"evt-inv-s4-{RUN_ID}", f"INV_SEV4_{RUN_ID}", "store-101", "network", "disable", "warning", "Invalid combo"),
)
check("disable+warning rejected", status == 422)


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


print("\n--- OK event for payments ---")
status, body = request(
    "POST",
    "/api/v1/events",
    event(f"evt-T04-{RUN_ID}", f"PAY_TIMEOUT_{RUN_ID}", "store-104", "payments", "ok", "info", "Gateway recovered"),
)
check("ok accepted", body.get("accepted") is True, body)


print("\n--- Green reset behavior ---")
status, body = request(
    "POST",
    "/api/v1/events",
    event(f"evt-T05-{RUN_ID}", f"LOY_FAIL_{RUN_ID}", "store-205", "loyalty", "problem", "critical", "Loyalty API down"),
)
check("critical alert accepted", body.get("accepted") is True, body)

status, body = request(
    "POST",
    "/api/v1/events",
    event(f"evt-T06-{RUN_ID}", f"LOY_OK_{RUN_ID}", "store-205", "loyalty", "ok", "info", "Loyalty recovered"),
)
check("ok signal accepted", body.get("accepted") is True, body)


print("\n--- One-shot stale expectation and disabled override behavior ---")
stale_seed = event(
    f"evt-stale-seed-{RUN_ID}",
    f"STALE_SEED_{RUN_ID}",
    "store-330",
    "daily-open",
    "ok",
    "info",
    "Daily open check-in healthy",
)
stale_seed["stale_interval"] = "30m"
status, body = request("POST", "/api/v1/events", stale_seed)
check("stale expectation seed accepted", body.get("accepted") is True, body)

stale_clear_event = event(
    f"evt-stale-clear-{RUN_ID}",
    f"STALE_CLEAR_{RUN_ID}",
    "store-330",
    "daily-open",
    "problem",
    "warning",
    "Daily open finished late",
)
status, body = request("POST", "/api/v1/events", stale_clear_event)
check("follow-up event without stale_interval accepted", body.get("accepted") is True, body)

status, bootstrap_after_clear = request("GET", "/api/v1/bootstrap")
store_330_after_clear = next(
    (s for s in bootstrap_after_clear.get("statuses", []) if s["store_id"] == "store-330" and s["component"] == "daily-open"),
    None,
)
check("post-clear entity present", store_330_after_clear is not None)
check(
    "stale expectation cleared when stale_interval omitted",
    store_330_after_clear and store_330_after_clear.get("stale_interval_seconds") is None,
    store_330_after_clear,
)

status, body = request(
    "POST",
    "/api/v1/events",
    event(
        f"evt-disabled-{RUN_ID}",
        f"DISABLED_{RUN_ID}",
        "store-330",
        "daily-open",
        "disable",
        "info",
        "Component disabled for maintenance",
    ),
)
check("disable accepted", body.get("accepted") is True, body)

status, body = request(
    "POST",
    "/api/v1/events",
    event(
        f"evt-disabled-problem-{RUN_ID}",
        f"DISABLED_PROB_{RUN_ID}",
        "store-330",
        "daily-open",
        "problem",
        "critical",
        "Problem emitted while disabled",
    ),
)
check("problem while disabled accepted", body.get("accepted") is True, body)

status, body = request("GET", "/api/v1/active-alerts?store_id=store-330&component=daily-open")
check("disabled component has no operationally active alerts", status == 200 and isinstance(body, list) and len(body) == 0, body)

status, body = request("GET", "/api/v1/entity-events?store_id=store-330&component=daily-open&hours=24")
check("events while disabled are still logged", status == 200 and any(item.get("event_id") == f"evt-disabled-problem-{RUN_ID}" for item in body), body)


print("\n--- Bootstrap endpoint ---")
status, bootstrap_body = request("GET", "/api/v1/bootstrap")
check("returns 200", status == 200)
check("has statuses list", isinstance(bootstrap_body.get("statuses"), list), bootstrap_body)
check("has recent_events list", isinstance(bootstrap_body.get("recent_events"), list), bootstrap_body)
check("has latest_sequence", isinstance(bootstrap_body.get("latest_sequence"), int), bootstrap_body)

store_104_payments = next(
    (s for s in bootstrap_body.get("statuses", []) if s["store_id"] == "store-104" and s["component"] == "payments"),
    None,
)
check("payments entity present", store_104_payments is not None)
check(
    "payments status is green after ok event",
    store_104_payments and store_104_payments.get("status_color") == "green",
    store_104_payments,
)

print("\n--- Entity 24-hour event history endpoint ---")
status, history_body = request("GET", f"/api/v1/entity-events?store_id=store-104&component=payments&hours=24")
check("entity-events returns 200", status == 200, history_body)
check("entity-events returns list", isinstance(history_body, list), history_body)
check(
    "entity-events include only requested store/component",
    all(item.get("store_id") == "store-104" and item.get("component") == "payments" for item in history_body),
    history_body,
)
check(
    "entity-events include all event types for component timeline",
    {"problem", "ok"}.issubset({item.get("event_type") for item in history_body}),
    history_body,
)

store_104_inv = next(
    (s for s in bootstrap_body.get("statuses", []) if s["store_id"] == "store-104" and s["component"] == "inventory"),
    None,
)
check(
    "inventory status is yellow (unresolved warning)",
    store_104_inv and store_104_inv.get("status_color") == "yellow",
    store_104_inv,
)
check(
    "network stale interval parsed to seconds",
    any(
        s.get("store_id") == "store-104"
        and s.get("component") == "network"
        and s.get("stale_interval_seconds") == 191400
        for s in bootstrap_body.get("statuses", [])
    ),
    bootstrap_body.get("statuses", []),
)

store_330_daily = next(
    (s for s in bootstrap_body.get("statuses", []) if s["store_id"] == "store-330" and s["component"] == "daily-open"),
    None,
)
check("daily-open entity present", store_330_daily is not None)
check(
    "disabled override keeps component white",
    store_330_daily and store_330_daily.get("status_color") == "white",
    store_330_daily,
)
check(
    "disabled component has zero active incidents",
    store_330_daily and store_330_daily.get("active_incident_count") == 0,
    store_330_daily,
)

store_205_loyalty = next(
    (s for s in bootstrap_body.get("statuses", []) if s["store_id"] == "store-205" and s["component"] == "loyalty"),
    None,
)
check("loyalty entity present", store_205_loyalty is not None)
check(
    "green signal resets loyalty status to green",
    store_205_loyalty and store_205_loyalty.get("status_color") == "green",
    store_205_loyalty,
)
check(
    "green signal clears loyalty active incident count",
    store_205_loyalty and store_205_loyalty.get("active_incident_count") == 0,
    store_205_loyalty,
)

status, body = request("GET", f"/api/v1/active-alerts?store_id=store-205&component=loyalty")
check("active-alerts for reset component returns 200", status == 200, body)
check("active-alerts list empty after green reset", isinstance(body, list) and len(body) == 0, body)


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


print("\n--- Hierarchy endpoints ---")
status, body = request("GET", "/api/v1/status/stores")
check("stores hierarchy returns 200", status == 200, body)
check("stores hierarchy returns list", isinstance(body, list), body)
check("stores hierarchy contains store-104", any(s.get("store_id") == "store-104" for s in body), body)

status, body = request("GET", "/api/v1/status/stores/store-104/components")
check("component hierarchy returns 200", status == 200, body)
check("component hierarchy returns list", isinstance(body, list), body)
check(
    "component hierarchy includes payments",
    any(c.get("store_id") == "store-104" and c.get("component") == "payments" for c in body),
    body,
)


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


print("\n--- Metadata round-trip ---")
meta_payload = {
    "event_id": f"evt-meta-{RUN_ID}",
    "dedup_key": f"meta-dk-{RUN_ID}",
    "store_id": "store-104",
    "component": "meta-component",
    "event_type": "problem",
    "severity": "warning",
    "message": "metadata round-trip test",
    "source": "smoke-test",
    "metadata": {"region": "west", "batch": 42, "tags": ["a", "b"]},
}
status, body = request("POST", "/api/v1/events", meta_payload)
check("metadata event accepted", status == 200 and body.get("accepted") is True, body)

status, body = request("GET", f"/api/v1/active-alerts?store_id=store-104&component=meta-component")
check("metadata event in active-alerts", status == 200 and any(e.get("event_id") == f"evt-meta-{RUN_ID}" for e in body), body)
meta_alert = next((e for e in body if e.get("event_id") == f"evt-meta-{RUN_ID}"), {})
check("active-alerts metadata field present", "metadata" in meta_alert, meta_alert)
check("active-alerts metadata values correct", meta_alert.get("metadata") == {"region": "west", "batch": 42, "tags": ["a", "b"]}, meta_alert.get("metadata"))

status, body = request("GET", f"/api/v1/entity-events?store_id=store-104&component=meta-component&hours=24")
check("metadata event in entity-events", status == 200 and any(e.get("event_id") == f"evt-meta-{RUN_ID}" for e in body), body)
meta_hist = next((e for e in body if e.get("event_id") == f"evt-meta-{RUN_ID}"), {})
check("entity-events metadata field present", "metadata" in meta_hist, meta_hist)
check("entity-events metadata values correct", meta_hist.get("metadata") == {"region": "west", "batch": 42, "tags": ["a", "b"]}, meta_hist.get("metadata"))

status, bootstrap_body = request("GET", "/api/v1/bootstrap")
recent_meta = next((e for e in bootstrap_body.get("recent_events", []) if e.get("event_id") == f"evt-meta-{RUN_ID}"), None)
if recent_meta is not None:
    check("bootstrap recent_events metadata field present", "metadata" in recent_meta, recent_meta)
    check("bootstrap recent_events metadata values correct", recent_meta.get("metadata") == {"region": "west", "batch": 42, "tags": ["a", "b"]}, recent_meta.get("metadata"))

status, body = request("POST", "/api/v1/events", {
    "event_id": f"evt-meta-ok-{RUN_ID}",
    "dedup_key": f"meta-dk-{RUN_ID}",
    "store_id": "store-104",
    "component": "meta-component",
    "event_type": "ok",
    "severity": "info",
    "message": "metadata round-trip recovery",
    "source": "smoke-test",
    "metadata": {},
})
check("metadata recovery accepted", status == 200 and body.get("accepted") is True, body)


print("\n--- Logs endpoints ---")
status, body = request("GET", "/api/v1/log-files", key=None)
check("log-files returns 200 without auth", status == 200, body)
check("log-files returns list", isinstance(body, list), body)

status, body = request("GET", "/api/v1/logs?limit=100&offset=0", key=None)
check("logs returns 200 without auth", status == 200, body)
check("logs response has items list", isinstance(body.get("items"), list), body)

status, body = request("GET", "/api/v1/logs?client_ip=127.0.0.1&limit=100&offset=0", key=None)
check("logs IP filter returns 200", status == 200, body)
check("logs IP filter contains only matching rows", all("127.0.0.1" in (item.get("client_ip") or "") for item in body.get("items", [])), body)

status, body = request("GET", f"/api/v1/logs?event_id=evt-T01-{RUN_ID}&limit=100&offset=0", key=None)
check("logs event_id filter returns 200", status == 200, body)
check(
    "logs event_id filter returns matching rows",
    all(f"evt-T01-{RUN_ID}" in (item.get("event_id") or "") for item in body.get("items", [])),
    body,
)


passed = sum(results)
failed = len(results) - passed
print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed out of {len(results)} checks")
if failed:
    sys.exit(1)

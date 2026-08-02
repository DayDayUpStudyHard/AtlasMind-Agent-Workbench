"""Test cancel + idempotency features."""
import json, time, urllib.request

AI_BASE = "http://localhost:18088"

# ── Test 1: Cancel ───────────────────────────────────────────────────
print("── 1. Cancel Test ──")

# Create a run via internal API
payload = {
    "requestId": f"cancel_test_{int(time.time())}",
    "runId": None, "projectId": 2, "taskType": "HEALTH_ANALYSIS",
    "question": "Cancel test", "actor": "test",
    "project": {"id": 2, "name": "mhz", "project_key": "MHZ"},
    "taskInput": {}, "options": {}
}

# First, create a run record in DB
import pymysql
conn = pymysql.connect(host="localhost", port=3306, user="root", password="123456",
                       database="atlasmind_agent", charset="utf8mb4")
with conn:
    cur = conn.cursor()
    cur.execute("INSERT INTO agent_run (project_id,run_type,trigger_type,question,status) VALUES (2,'HEALTH_ANALYSIS','MANUAL','Cancel test','CREATED')")
    conn.commit()
    run_id = cur.lastrowid
print(f"  Created run {run_id}")

# Start the run
payload["runId"] = run_id
req = urllib.request.Request(f"{AI_BASE}/internal/agent/run",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"}, method="POST")
resp = json.loads(urllib.request.urlopen(req).read())
print(f"  Started: {resp['status']}")

# Wait a moment for harness to start, then cancel
time.sleep(2)
cancel_req = urllib.request.Request(f"{AI_BASE}/internal/agent/run/{run_id}/cancel",
    data=json.dumps({"reason": "Test cancel"}).encode(),
    headers={"Content-Type": "application/json"}, method="POST")
cancel_resp = json.loads(urllib.request.urlopen(cancel_req).read())
print(f"  Cancel requested: {cancel_resp['status']}")

# Poll - should stop quickly now
for i in range(15):
    time.sleep(1)
    req = urllib.request.Request(f"{AI_BASE}/internal/agent/run/{run_id}")
    rd = json.loads(urllib.request.urlopen(req).read())
    run_status = rd.get("run", {}).get("status", "")
    if run_status in ("CANCELLED", "FAILED", "COMPLETED"):
        print(f"  Final after {i+1}s: {run_status}")
        break
    if i % 3 == 0:
        print(f"  poll {i}s: {run_status}")
cancel_ok = run_status == "CANCELLED"
print(f"  Cancel test: {'✅ PASS' if cancel_ok else '❌ FAIL'}")

# ── Test 2: Idempotency ──────────────────────────────────────────────
print("\n── 2. Idempotency Test ──")

req_id = f"idem_test_{int(time.time())}"

# Create another run
with conn:
    cur = conn.cursor()
    cur.execute("INSERT INTO agent_run (project_id,run_type,trigger_type,question,status) VALUES (2,'HEALTH_ANALYSIS','MANUAL','Idem test','CREATED')")
    conn.commit()
    run_id2 = cur.lastrowid
print(f"  Created run {run_id2}")

payload2 = {**payload, "requestId": req_id, "runId": run_id2}
req = urllib.request.Request(f"{AI_BASE}/internal/agent/run",
    data=json.dumps(payload2).encode(),
    headers={"Content-Type": "application/json"}, method="POST")
r1 = json.loads(urllib.request.urlopen(req).read())
print(f"  Call 1: {r1['status']} - '{r1['currentStep']}'")

# Call again with same requestId
req = urllib.request.Request(f"{AI_BASE}/internal/agent/run",
    data=json.dumps(payload2).encode(),
    headers={"Content-Type": "application/json"}, method="POST")
r2 = json.loads(urllib.request.urlopen(req).read())
print(f"  Call 2 (same requestId): {r2['status']} - '{r2['currentStep']}'")

idem_ok = r2["currentStep"] == "任务已在调度中"
print(f"  Idempotency test: {'✅ PASS' if idem_ok else '❌ FAIL'}")

conn.close()
print(f"\n{'═'*40}")
print(f"{'ALL PASSED!' if (cancel_ok and idem_ok) else 'SOME FAILED'}")

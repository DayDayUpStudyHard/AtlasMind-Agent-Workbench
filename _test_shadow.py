"""Shadow Run test: set AGENT_RUNTIME=python, trigger run via Java API, compare results."""
import json
import urllib.request
import urllib.error

BASE = "http://localhost:18080"
AI_BASE = "http://localhost:18088"
PROJECT_ID = 2


def api(method, path, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["atlasmind-token"] = token
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return {"error": e.code, "body": body[:500]}


# Step 1: Login
login_resp = api("POST", "/api/auth/login", {"username": "admin", "password": "admin123"})
token = login_resp.get("data", {}).get("token", "")
print(f"1. Login: {'OK' if token else 'FAILED'}")

# Step 2: Set AGENT_RUNTIME mode (via Python query endpoint or direct DB)
# For now, test with "python" mode by checking current config
import pymysql
conn = pymysql.connect(
    host="localhost", port=3306, user="root", password="123456",
    database="atlasmind_agent", charset="utf8mb4",
)
with conn:
    cur = conn.cursor()
    cur.execute("UPDATE system_config SET config_value='python' WHERE config_key='AGENT_RUNTIME'")
    conn.commit()
    cur.execute("SELECT config_value FROM system_config WHERE config_key='AGENT_RUNTIME'")
    mode = cur.fetchone()[0]
    print(f"2. AGENT_RUNTIME = {mode}")

# Step 3: Trigger run via Java
run_resp = api("POST", f"/api/workspace/projects/{PROJECT_ID}/runs",
               {"taskType": "HEALTH_ANALYSIS", "question": "Shadow test via Java→Python bridge",
                "triggerType": "MANUAL"}, token)
if "error" in run_resp:
    print(f"3. Run creation FAILED: {run_resp}")
    import sys
    sys.exit(1)

run_data = run_resp.get("data", {})
run_id = run_data.get("id")
print(f"3. Run {run_id} created: status={run_data.get('status')}")

# Step 4: Poll until completion
import time
for i in range(60):
    detail = api("GET", f"/api/workspace/projects/runs/{run_id}", token=token)
    rd = detail.get("data", {})
    status = rd.get("status", "")
    progress = rd.get("progress", 0)
    print(f"   Poll {i}: status={status} progress={progress}%")
    if status in ("COMPLETED", "FAILED", "CANCELLED", "WAITING_APPROVAL"):
        break
    time.sleep(3)

# Step 5: Show results
print(f"\n=== Final Result ===")
report = rd.get("report") or {}
print(f"status={status}  progress={progress}%")
print(f"error_message={rd.get('errorMessage', '')}")
if report:
    print(f"health_score={report.get('healthScore')}  health_status={report.get('healthStatus')}")
    print(f"scoring_version={report.get('scoringVersion')}")
    print(f"evidence_hash={report.get('evidenceHash', '')[:50]}")
    dims = report.get("dimensionsJson") or "[]"
    if isinstance(dims, str):
        dims = json.loads(dims)
    for d in dims:
        print(f"  {d['name']}: {d['score']}/100 (weight {d.get('weight', '?')})")

"""E2E test after cleanup: verify Python bridge works."""
import json, time, urllib.request

BASE = "http://localhost:18080"

# Login
req = urllib.request.Request(f"{BASE}/api/auth/login",
    data=json.dumps({"username":"admin","password":"admin123"}).encode(),
    headers={"Content-Type":"application/json"}, method="POST")
token = json.loads(urllib.request.urlopen(req).read())["data"]["token"]
print(f"Login OK, token={token[:20]}...")

# Create run
headers = {"Content-Type":"application/json", "atlasmind-token": token}
req = urllib.request.Request(f"{BASE}/api/workspace/projects/2/runs",
    data=json.dumps({"taskType":"HEALTH_ANALYSIS","question":"Test after cleanup","triggerType":"MANUAL"}).encode(),
    headers=headers, method="POST")
run_data = json.loads(urllib.request.urlopen(req).read())["data"]
run_id = run_data["id"]
print(f"Run {run_id} created: status={run_data['status']}")

# Poll
for i in range(40):
    time.sleep(3)
    req = urllib.request.Request(f"{BASE}/api/workspace/projects/runs/{run_id}", headers=headers)
    rd = json.loads(urllib.request.urlopen(req).read())["data"]
    s = rd.get("status",""); p = rd.get("progress",0)
    if i % 5 == 0: print(f"  poll {i}: {s} {p}%")
    if s in ("COMPLETED","FAILED","CANCELLED","WAITING_APPROVAL"):
        break

print(f"Final: status={s} progress={p}%")
report = rd.get("report") or {}
if report:
    print(f"  healthScore={report.get('healthScore')}  healthStatus={report.get('healthStatus')}  hash={str(report.get('evidenceHash',''))[:30]}...")
    print(f"  scoringVersion={report.get('scoringVersion')}")
    dims = report.get("dimensionsJson", "[]")
    if isinstance(dims, str): dims = json.loads(dims)
    for d in dims: print(f"  {d['name']}: {d['score']}/100 (w{d.get('weight','?')})")
if s == "FAILED": print(f"  ERROR: {str(rd.get('errorMessage',''))[:200]}")
print("TEST PASSED!" if s in ("COMPLETED","WAITING_APPROVAL") else "TEST FAILED!")

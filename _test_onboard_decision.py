"""Test onboarding and decision runs after fixes."""
import json, time, urllib.request, pymysql

BASE = "http://localhost:18080"
req = urllib.request.Request(f"{BASE}/api/auth/login",
    data=json.dumps({"username":"admin","password":"admin123"}).encode(),
    headers={"Content-Type":"application/json"}, method="POST")
token = json.loads(urllib.request.urlopen(req).read())["data"]["token"]
headers = {"Content-Type":"application/json", "atlasmind-token": token}
print("Logged in OK")

# Create Onboarding
resp = json.loads(urllib.request.urlopen(urllib.request.Request(
    f"{BASE}/api/workspace/projects/2/runs",
    data=json.dumps({"taskType":"PROJECT_ONBOARDING",
        "question":"为新加入的后端开发工程师生成项目接手手册",
        "triggerType":"MANUAL",
        "inputJson":{"role":"后端开发","level":"高级"}}).encode(),
    headers=headers, method="POST")).read())
onboard_id = resp["data"]["id"]
print(f"Onboarding Run {onboard_id} created")

# Create Decision
resp = json.loads(urllib.request.urlopen(urllib.request.Request(
    f"{BASE}/api/workspace/projects/2/runs",
    data=json.dumps({"taskType":"ENGINEERING_DECISION",
        "question":"Should we migrate from MySQL to PostgreSQL for JSON support?",
        "triggerType":"MANUAL",
        "inputJson":{"constraints":["team MySQL experience","need JSONB","budget limited"]}}).encode(),
    headers=headers, method="POST")).read())
decision_id = resp["data"]["id"]
print(f"Decision Run {decision_id} created")

# Wait
print("Waiting (max 180s)...")
conn = pymysql.connect(host="localhost", port=3306, user="root", password="123456",
                       database="atlasmind_agent", charset="utf8mb4")
deadline = time.time() + 180
pending = {onboard_id: "ONBOARD", decision_id: "DECISION"}
while pending and time.time() < deadline:
    conn2 = pymysql.connect(host="localhost", port=3306, user="root", password="123456",
                           database="atlasmind_agent", charset="utf8mb4")
    try:
        with conn2:
            cur = conn2.cursor()
            for rid, label in list(pending.items()):
                cur.execute("SELECT status, progress, current_step FROM agent_run WHERE id=%s", (rid,))
                row = cur.fetchone()
                if row and row[0] in ("COMPLETED", "FAILED", "CANCELLED"):
                    print(f"  Run {rid} ({label}): {row[0]}")
                    pending.pop(rid)
                elif row and row[0] != "CREATED":
                    print(f"  Run {rid} ({label}): {row[0]}@{row[1]}% - {row[2] or ''}")
    except Exception as e:
        print(f"  DB error: {e}")
    if pending:
        time.sleep(4)

if pending:
    print(f"TIMEOUT: {pending} still running")
else:
    print("All completed!")

# Check reports
conn3 = pymysql.connect(host="localhost", port=3306, user="root", password="123456",
                       database="atlasmind_agent", charset="utf8mb4")
print("\n=== Report Quality ===")
for rid, label in [(onboard_id, "ONBOARDING"), (decision_id, "DECISION")]:
    with conn3:
        cur = conn3.cursor()
        cur.execute("SELECT title, summary, LENGTH(content_json) as clen, LENGTH(report_markdown) as mlen, status FROM agent_report WHERE run_id=%s", (rid,))
        row = cur.fetchone()
        if row:
            title = row[0] or "NONE"
            summary = (row[1] or "NONE")[:80]
            print(f"  [{label}] title={title} content={row[2]}bytes markdown={row[3]}bytes status={row[4]}")
            if row[2] and row[2] < 200:
                print(f"    WARN: content too short!")
                cur.execute("SELECT content_json FROM agent_report WHERE run_id=%s", (rid,))
                c = cur.fetchone()
                if c: print(f"    content={str(c[0])[:200]}")
        else:
            print(f"  [{label}] No report found!")

print("\n=== Action Proposals ===")
for rid, label in [(onboard_id, "ONBOARDING"), (decision_id, "DECISION")]:
    with conn3:
        cur = conn3.cursor()
        cur.execute("SELECT COUNT(*) as cnt, GROUP_CONCAT(action_type) as types FROM agent_action WHERE run_id=%s", (rid,))
        row = cur.fetchone()
        print(f"  [{label}] {row[0]} action(s): {row[1] or 'none'}")

conn3.close()
print("\nDone!")

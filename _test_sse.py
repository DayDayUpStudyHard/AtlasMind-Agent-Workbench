"""Test SSE progress events via Redis PubSub."""
import json, time, urllib.request, threading, redis

BASE = "http://localhost:18080"
AI_BASE = "http://localhost:18088"

# Login
req = urllib.request.Request(f"{BASE}/api/auth/login",
    data=json.dumps({"username":"admin","password":"admin123"}).encode(),
    headers={"Content-Type":"application/json"}, method="POST")
token = json.loads(urllib.request.urlopen(req).read())["data"]["token"]
headers = {"Content-Type":"application/json", "atlasmind-token": token}

# Create run
req = urllib.request.Request(f"{BASE}/api/workspace/projects/2/runs",
    data=json.dumps({"taskType":"HEALTH_ANALYSIS","question":"SSE test","triggerType":"MANUAL"}).encode(),
    headers=headers, method="POST")
run_id = json.loads(urllib.request.urlopen(req).read())["data"]["id"]
print(f"Run {run_id} created")

# Subscribe to SSE via Redis
r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
pubsub = r.pubsub()
pubsub.subscribe(f"run:{run_id}:progress")
print(f"Subscribed to run:{run_id}:progress")

# Poll for SSE events
events = []
deadline = time.time() + 120
while time.time() < deadline:
    msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=2.0)
    if msg:
        data = json.loads(msg["data"])
        short = f"[{data['phase']}] {data['progress']}% {data['currentStep']}"
        if short not in events:  # dedup
            events.append(short)
            print(f"  SSE: {short}")
        if data["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
            break
    else:
        # Check if run completed via DB
        import pymysql
        conn = pymysql.connect(host="localhost", port=3306, user="root", password="123456",
                               database="atlasmind_agent", charset="utf8mb4")
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT status, progress FROM agent_run WHERE id=%s", (run_id,))
            row = cur.fetchone()
            if row and row[0] in ("COMPLETED", "FAILED", "CANCELLED"):
                print(f"  Run finished: {row[0]} {row[1]}%")
                break

pubsub.unsubscribe()
r.close()

print(f"\nReceived {len(events)} unique SSE events")
print("SSE TEST PASSED!" if len(events) >= 2 else "SSE TEST FAILED!")

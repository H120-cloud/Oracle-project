import subprocess
import time
import sys
import os
import signal

os.chdir(r"c:\Users\Husna\OneDrive\Desktop\Oracle project1")

# 1. Kill any process on port 8080
print("[1/4] Checking for existing server on port 8080...")
try:
    result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if ":8080" in line and "LISTENING" in line:
            parts = line.strip().split()
            if len(parts) >= 5:
                pid = parts[-1]
                print(f"   Killing PID {pid} on port 8080")
                subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
except Exception as e:
    print(f"   Warning: {e}")

time.sleep(2)

# 2. Start uvicorn server
print("[2/4] Starting uvicorn server...")
log_file = open("server_backfill.log", "w", encoding="utf-8")
server = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-use-colors"],
    stdout=log_file,
    stderr=subprocess.STDOUT,
    text=True,
)

# 3. Wait for startup
print("[3/4] Waiting for server to start...")
startup_msg = ""
start_time = time.time()
ready = False

while time.time() - start_time < 30:
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:8080/api/v1/news-momentum/backfill/status")
        with urllib.request.urlopen(req, timeout=2) as resp:
            print("   Server is ready!")
            ready = True
            break
    except Exception:
        # Check if server process died
        if server.poll() is not None:
            print("   SERVER DIED! Check server_backfill.log for details")
            sys.exit(1)
        time.sleep(1)

if not ready:
    print("   Server did not start within 30 seconds")
    print("   Check server_backfill.log for details")
    server.terminate()
    sys.exit(1)

# 4. Run backfill (fire-and-forget, then poll status)
print("[4/4] Running backfill...")
import json
job_id = None
try:
    import urllib.request
    req = urllib.request.Request(
        "http://localhost:8080/api/v1/news-momentum/backfill",
        data=json.dumps({
            "tickers": "AAPL,TSLA,NVDA,AMD,MSFT",
            "start_date": "2025-01-01",
            "end_date": "2025-01-31",
            "news_limit": 100,
            "max_concurrent": 2,
            "force": True
        }).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode())
        print(f"Backfill started: {json.dumps(result, indent=2)}")
        job_id = result.get("job_id")
except Exception as e:
    print(f"BACKFILL START ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 5. Poll status until done
print("\nPolling backfill status every 30 seconds...")
start_time = time.time()
last_record_count = 0
while True:
    time.sleep(30)
    try:
        req = urllib.request.Request("http://localhost:8080/api/v1/news-momentum/backfill/status")
        with urllib.request.urlopen(req, timeout=20) as resp:
            status = json.loads(resp.read().decode())
            records = status.get("records", {})
            total = records.get("total_backfill_records", 0)
            active = status.get("active_jobs", 0)
            recent = status.get("recent_jobs", {})
            job = recent.get(job_id, {}) if job_id else {}
            job_status = job.get("status", "unknown")
            elapsed = int(time.time() - start_time)
            print(f"[{elapsed}s] Status: {job_status} | Records: {total} | Active jobs: {active}")
            if job_status == "completed":
                print("\n=== BACKFILL COMPLETE ===")
                print(json.dumps(status, indent=2))
                break
            if job_status == "failed":
                print("\n=== BACKFILL FAILED ===")
                print(json.dumps(status, indent=2))
                break
            if active == 0 and total > last_record_count:
                last_record_count = total
    except Exception as e:
        print(f"  Poll error: {e}")

print("\nDone! Keeping server running...")
print("Press Ctrl+C to stop.")
try:
    server.wait()
except KeyboardInterrupt:
    server.terminate()
    print("Server stopped.")

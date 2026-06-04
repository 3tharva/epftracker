import subprocess
import time
import urllib.request
import urllib.error
import sys

print("[*] Launching run_dashboard.py server (unbuffered)...")
server_proc = subprocess.Popen(
    [sys.executable, "-u", "run_dashboard.py"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True
)

# Wait 3 seconds for server to start
time.sleep(3)

print("[*] Sending test POST request to /api/start with X-Mode: payment...")
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/start",
    method="POST",
    headers={
        "X-Headless": "true",
        "X-Sleep": "10",
        "X-Workers": "2",
        "X-Mode": "payment",
        "X-Api-Key": "dummy-key"
    }
)

try:
    with urllib.request.urlopen(req) as response:
        res_body = response.read().decode()
        print(f"[+] Response status: {response.status}")
        print(f"[+] Response body: {res_body}")
except urllib.error.HTTPError as e:
    print(f"[!] HTTP Error: {e.code} - {e.reason}")
    print(e.read().decode())
except Exception as e:
    print(f"[!] Error connecting to server: {e}")

# Wait 4 seconds to let the subprocess start and output text
time.sleep(4)

print("[*] Terminating dashboard server...")
server_proc.terminate()
try:
    stdout_data, _ = server_proc.communicate(timeout=5)
except Exception:
    server_proc.kill()
    stdout_data, _ = server_proc.communicate()

print("\n----- DASHBOARD SERVER STDOUT LOG -----")
print(stdout_data)
print("---------------------------------------")

if "vendor_scraper.py" in stdout_data and "--payment" in stdout_data:
    print("[SUCCESS] Subprocess spawned with --payment flag successfully!")
else:
    print("[FAIL] Subprocess command matching --payment was NOT found in dashboard logs.")

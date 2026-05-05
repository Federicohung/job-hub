"""Job Hub: run scraper and push updated data to GitHub"""
import subprocess, sys, os

HUB_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = r"C:\Program Files\AutoClaw\resources\python\python.exe"
SCRAPER = os.path.join(HUB_DIR, "scraper", "scraper.py")

print("=== Job Hub Refresh START ===")

# 1. Run scraper
print("[1/3] Running scraper...")
result = subprocess.run(
    [PYTHON, SCRAPER],
    cwd=os.path.join(HUB_DIR, "scraper"),
    capture_output=True, text=True, timeout=180
)
print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
if result.returncode != 0:
    print(f"Scraper stderr: {result.stderr[-300:]}")

# 2. Check if data changed
print("[2/3] Checking changes...")
subprocess.run(["git", "add", "scraper/data/jobs.json"], cwd=HUB_DIR, check=True)
diff = subprocess.run(
    ["git", "diff", "--cached", "--quiet"],
    cwd=HUB_DIR, capture_output=True
)
if diff.returncode == 0:
    print("No changes to push.")
    print("=== Job Hub Refresh DONE (no changes) ===")
    sys.exit(0)

# 3. Commit and push
print("[3/3] Pushing to GitHub...")
subprocess.run(
    ["git", "config", "user.name", "job-hub-bot"],
    cwd=HUB_DIR, check=True, capture_output=True
)
subprocess.run(
    ["git", "config", "user.email", "job-hub-bot@users.noreply.github.com"],
    cwd=HUB_DIR, check=True, capture_output=True
)

import datetime
msg = f"🦞 job data update {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
subprocess.run(["git", "commit", "-m", msg], cwd=HUB_DIR, check=True, capture_output=True)

push = subprocess.run(
    ["git", "push", "origin", "master"],
    cwd=HUB_DIR, capture_output=True, text=True
)
print(push.stdout)
if push.returncode != 0:
    print(f"Push error: {push.stderr}")

print("=== Job Hub Refresh DONE ===")

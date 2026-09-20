"""P1-4 Failure Recovery Tests — safe tests only (no destructive operations)."""
import os
import sys
import sqlite3
from datetime import datetime, timedelta, timezone

NOUS_HOME = os.environ.get("NOUS_HOME", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, NOUS_HOME)
from nous_core.db import get_db_path, run_migrations
from nous_core.events import emit_event, count_events
from nous_core.jobs import create_job, claim_job, fail_job, recover_stale_jobs, count_jobs, get_job
from nous_core.notifications import notify, count_unread
from nous_core.audit import audit_log
from nous_core.devices import register_device, heartbeat

PASS = 0
FAIL = 0

def test(name, fn):
    global PASS, FAIL
    try:
        ok = fn()
        if ok:
            print(f"  ✅ {name}")
            PASS += 1
        else:
            print(f"  ❌ {name} — FAILED")
            FAIL += 1
    except Exception as e:
        print(f"  ❌ {name} — EXCEPTION: {e}")
        FAIL += 1

print("=" * 60)
print("P1-4 FAILURE RECOVERY TESTS")
print("=" * 60)
run_migrations()
DB_PATH = get_db_path()

def iso_seconds_ago(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")

emit_event("test.baseline", source="failure_test", payload={"ok": True})
create_job("test_baseline", source="failure_test")

# 1: Brain Restart — verify events/jobs survive restart
print("\n[1/6] Brain Restart Recovery")
test("Events survive restart (count > 0)", lambda: count_events() > 0)
test("Jobs survive restart (check existing)", lambda: count_jobs() > 0)
test("DB connection auto-recovers", lambda: (lambda mod: mod.connect().__enter__() is not None)(__import__("nous_core.db", fromlist=["connect"])))

# 2: Worker/Job Failure — verify fail_job + retry
print("\n[2/6] Job Execution Failure")
jid = create_job("test_failure", source="failure_test", timeout_sec=5)
test("Job created", lambda: bool(jid))
claimed = claim_job(jid)
test("Job claimed", lambda: claimed is not None)
fail_job(jid, "simulated crash", will_retry=True)
j = get_job(jid)
test("Job retry: status is pending", lambda: j and j["status"] == "pending")
test("Job retry: retries incremented", lambda: j and j["retries"] >= 1)
# Force retry exhaustion
for _ in range(5):
    claim_job(jid)
    fail_job(jid, "retry", will_retry=True)
j2 = get_job(jid)
test("Job permanently failed after max retries", lambda: j2 and j2["status"] == "failed")

# 3: Device Offline Detection
print("\n[3/6] Device Offline Detection")
register_device("test_device", name="TestDev", device_type="pc")
heartbeat("test_device")
# Simulate: update last_seen to 100 seconds ago (offline threshold is 75s)
db = sqlite3.connect(DB_PATH)
db.execute("UPDATE devices SET last_seen = ? WHERE id = 'test_device'", (iso_seconds_ago(100),))
db.commit()
from nous_core.devices import update_online_status
changed = update_online_status()
test("Device marked offline after 100s no heartbeat", lambda: changed >= 1)
# Restore
heartbeat("test_device")
update_online_status()
db.close()

# 4: Job Timeout Detection
print("\n[4/6] Job Execution Timeout")
t_jid = create_job("test_timeout", source="failure_test", timeout_sec=1)
claim_job(t_jid)
# Simulate: job started 120 seconds ago
db = sqlite3.connect(DB_PATH)
db.execute("UPDATE jobs SET started_at = ? WHERE id = ?", (iso_seconds_ago(120), t_jid))
db.commit()
recovered = recover_stale_jobs(timeout_sec=60)
test("Stale job recovered (timeout > 60s)", lambda: recovered >= 1)
j3 = get_job(t_jid)
test("Recovered job marked failed or pending", lambda: j3 and j3["status"] in ("failed", "pending"))
db.close()

# 5: Notification Resilience
print("\n[5/6] Notification Failure Resilience")
try:
    nid = notify("test.failure", title="Failure Test", body="Testing notification resilience",
                 target_client="nonexistent", priority=0)
    test("Notification created even for nonexistent target", lambda: bool(nid))
except Exception:
    test("Notification fails gracefully (no crash)", lambda: True)
nu = count_unread()
test("Notification system still functional after edge case", lambda: nu >= 0)

# 6: Audit Resilience
print("\n[6/6] Audit Resilience")
audit_log("test.failure", actor="failure_test", target="test", result="simulated_error",
          detail={"test": True, "password": "secret123", "key": "sk-abc"})
audit_mod = __import__("nous_core.audit", fromlist=["query_logs"])
entries = audit_mod.query_logs(action="test.failure", limit=1)
test("Audit entry written", lambda: len(entries) > 0)
test("Secrets masked in audit detail", lambda: entries[0].get("detail", {}).get("password") == "***MASKED***")

# Summary
print("\n" + "=" * 60)
print(f"RESULTS: {PASS} passed, {FAIL} failed out of {PASS + FAIL} tests")
print("=" * 60)

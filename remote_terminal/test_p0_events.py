"""Test P0 components with real triggers."""
import os
import sys

NOUS_HOME = os.environ.get("NOUS_HOME", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, NOUS_HOME)

from nous_core.db import run_migrations
from nous_core.devices import register_device, heartbeat, list_devices
from nous_core.events import emit_event, count_events
from nous_core.jobs import create_job, claim_job, complete_job, count_jobs
from nous_core.notifications import notify, count_unread, mark_all_read
from nous_core.audit import audit_log, count_actions

print("=== P0 COMPONENT TEST ===")
run_migrations()

# 1. DEVICES
print("\n[1] Devices:")
register_device("laptop", name="TestPC", device_type="pc", host="192.0.2.10", port=8765, capabilities=["shell.exec", "screen.screenshot"])
register_device("phone", name="TestPhone", device_type="phone", host="192.0.2.11", port=8788, capabilities=["phone.tap", "audio.record"])
heartbeat("laptop")
heartbeat("phone")
for d in list_devices():
    print(f"  {d['id']}: online={d['is_online']}, capabilities={d['capabilities']}")

# 2. EVENTS
print("\n[2] Events:")
before = count_events()
emit_event("chat.message.received", source="phone", session_id="test-sid", payload={"model": "deepseek", "message_length": 10})
emit_event("tool.executed", source="run_command", session_id="test-sid", payload={"command": "dir", "output_length": 100})
emit_event("tool.confirmation_required", source="run_command", session_id="test-sid", payload={"confirmation_id": "test-cid", "command": "rm", "dangers": ["file_delete"]})
emit_event("session.created", source="phone", session_id="test-sid")
emit_event("device.heartbeat", source="brain", device_id="laptop", payload={"host": "192.0.2.10"})
now = count_events()
print(f"  {before} -> {now} events (+{now - before})")

# 3. JOBS
print("\n[3] Jobs:")
jb = count_jobs()
jid1 = create_job("confirmation", source="run_command", session_id="test-sid", payload={"command": "test-cmd", "dangers": ["test"]}, timeout_sec=60)
jid2 = create_job("cleanup", source="brain", timeout_sec=300)
print(f"  Created: {jid1}, {jid2}")
claimed = claim_job(jid1)
print(f"  Claimed {jid1}: status={claimed['status'] if claimed else 'FAIL'}")
if claimed:
    complete_job(jid1, {"result": "ok"})
    print(f"  Completed {jid1}")
ja = count_jobs()
print(f"  {jb} -> {ja} jobs (+{ja - jb})")

# 4. NOTIFICATIONS
print("\n[4] Notifications:")
nid1 = notify("test.info", title="Health Check", body="P0 test notification", target_client="phone", priority=1)
nid2 = notify("test.warning", title="Test Warning", body="Something to check", target_client="watch", priority=2)
print(f"  Created: {nid1}, {nid2}")
nu = count_unread(target_client="phone")
print(f"  Unread for phone: {nu}")
print(f"  Unread for watch: {count_unread(target_client='watch')}")
mark_all_read(target_client="phone")
print(f"  After mark_read(phone): {count_unread(target_client='phone')} unread")

# 5. AUDIT
print("\n[5] Audit:")
audit_log("tool.executed", actor="phone", target="test_tool", session_id="test-sid", result="success", detail={"output_length": 42})
audit_log("command.blocked", actor="phone", target="run_command", session_id="test-sid", result="awaiting_confirmation", detail={"dangers": ["test"]})
audit_log("confirmation.approved", actor="phone", target="run_command", session_id="test-sid", result="approved")
print(f"  Total entries: {count_actions()}")

# 6. VERIFY (read back)
print("\n[6] Verify read-back:")
from nous_core.events import list_events
evts = list_events(session_id="test-sid")
print(f"  Events for test-sid: {len(evts)}")
for e in evts:
    print(f"    {e['type']} (processed={e['processed']})")

from nous_core.jobs import list_jobs
jobs = list_jobs(session_id="test-sid")
print(f"  Jobs for test-sid: {len(jobs)}")
for j in jobs:
    print(f"    {j['type']}: {j['status']}")

from nous_core.audit import query_logs
auds = query_logs(session_id="test-sid")
print(f"  Audit entries for test-sid: {len(auds)}")
for a in auds:
    print(f"    {a['action']}: {a['result']}")

print("\n=== ALL TESTS DONE ===")

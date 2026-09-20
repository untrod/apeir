#!/usr/bin/env python3
"""P1-1 Kernel Health Check — runs on server."""
import sqlite3
import subprocess

import os
DB = os.path.join(os.environ.get("NOUS_HOME", os.path.dirname(os.path.abspath(__file__))), "data", "nous_core.db")
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

print("=" * 60)
print("P1-1 KERNEL HEALTH CHECK")
print("=" * 60)

# 1. Migrations
tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
print(f"\n[Migrations] {len(tables)} tables: {', '.join(tables)}")
for m in db.execute("SELECT * FROM schema_migrations ORDER BY version"):
    print(f"  v{m['version']}: {m['name']} ({m['applied_at'][:19]})")

# 2. Events
total = db.execute("SELECT COUNT(*) as n FROM events").fetchone()["n"]
by_type = db.execute("SELECT type, COUNT(*) as n FROM events GROUP BY type ORDER BY n DESC").fetchall()
unproc = db.execute("SELECT COUNT(*) as n FROM events WHERE processed=0").fetchone()["n"]
print(f"\n[2/8 Events] {total} total, {unproc} unprocessed")
for e in by_type:
    print(f"  {e['type']}: {e['n']}")

# 3. Jobs
jobs = db.execute("SELECT status, COUNT(*) as n FROM jobs GROUP BY status").fetchall()
print(f"\n[3/8 Jobs] {sum(j['n'] for j in jobs)} total")
for j in jobs:
    print(f"  {j['status']}: {j['n']}")
stale = db.execute("SELECT COUNT(*) as n FROM jobs WHERE status='running' AND started_at != ''").fetchone()["n"]
if stale:
    print(f"  WARNING: {stale} stale running jobs")

# 4. Devices
devs = db.execute("SELECT id, name, device_type, is_online, last_seen FROM devices").fetchall()
print(f"\n[4/8 Devices] {len(devs)} registered")
for d in devs:
    ls = d["last_seen"][:19] if d["last_seen"] else "never"
    print(f"  {d['id']} ({d['device_type']}): online={d['is_online']}, seen={ls}")

# 5. Notifications
ntotal = db.execute("SELECT COUNT(*) as n FROM notifications").fetchone()["n"]
nunread = db.execute("SELECT COUNT(*) as n FROM notifications WHERE read_at=''").fetchone()["n"]
nexpired = db.execute("SELECT COUNT(*) as n FROM notifications WHERE read_at='' AND datetime(created_at, '+' || ttl_sec || ' seconds') < datetime('now')").fetchone()["n"]
print(f"\n[5/8 Notifications] {ntotal} total, {nunread} unread, {nexpired} expired")
by_ntype = db.execute("SELECT type, COUNT(*) as n FROM notifications GROUP BY type").fetchall()
for n in by_ntype:
    print(f"  {n['type']}: {n['n']}")

# 6. Skills (from events)
skill_events = db.execute("SELECT type, COUNT(*) as n FROM events WHERE type LIKE 'skill.%' GROUP BY type").fetchall()
print(f"\n[6/8 Skills] {sum(s['n'] for s in skill_events)} skill events")
for s in skill_events:
    print(f"  {s['type']}: {s['n']}")

# 7. Automation
rules = db.execute("SELECT name, enabled, event_pattern, action_type, fire_count, last_fired_at FROM automation_rules ORDER BY priority DESC").fetchall()
alogs = db.execute("SELECT COUNT(*) as n FROM automation_log").fetchone()["n"]
print(f"\n[7/8 Automation] {len(rules)} rules, {alogs} log entries")
for r in rules:
    lf = r["last_fired_at"][:19] if r["last_fired_at"] else "never"
    print(f"  {'ON' if r['enabled'] else 'OFF'} {r['name']}: {r['event_pattern']} -> {r['action_type']} (fired {r['fire_count']}x, last={lf})")

# 8. Audit
atotal = db.execute("SELECT COUNT(*) as n FROM audit_logs").fetchone()["n"]
aby = db.execute("SELECT action, result, COUNT(*) as n FROM audit_logs GROUP BY action, result").fetchall()
print(f"\n[8/8 Audit] {atotal} entries")
for a in aby:
    print(f"  {a['action']}: {a['result']} x{a['n']}")

# Log tail
print("\n[Log] brain.log:")
log_path = os.path.join(os.environ.get("NOUS_HOME", os.path.dirname(os.path.abspath(__file__))), "brain.log")
out = subprocess.run(["tail", "-20", log_path], capture_output=True, text=True)
for line in out.stdout.splitlines():
    if any(kw in line.lower() for kw in ["nous_core", "p0", "dispatcher", "error", "failed", "timeout"]):
        print(f"  {line.strip()[:180]}")

print("\n" + "=" * 60)
print("HEALTH CHECK COMPLETE")
print("=" * 60)
db.close()

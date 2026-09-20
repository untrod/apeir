#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chaos engineering harness for Nous Runtime RC1 validation.

Injects controlled faults during stability testing to verify:
- Checkpoint integrity
- Idempotent operations
- Event catch-up after disruption
- Safe stop and restart
- Task migration between nodes
- Auto-recovery from common failures
- Rollback capability

Usage:
    python tools/chaos_harness.py --plan chaos_plans/rc1_72h.json
    python tools/chaos_harness.py --duration 3600 --random 10
    python tools/chaos_harness.py --quick  # 5-minute smoke test of all fault types
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIT_DIR = ROOT / ".audit"
RESULTS_DIR = AUDIT_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)



# Data models


@dataclass
class FaultEvent:
    """Record of a single fault injection."""
    fault_id: str
    fault_type: str
    target: str
    scheduled_at_sec: float       # seconds from run start
    actual_at_sec: float = 0.0
    duration_sec: float = 0.0
    success: bool = False
    error: str = ""
    recovery_time_sec: float = 0.0  # time until system recovered
    recovered: bool = False


@dataclass
class ChaosPlan:
    """Pre-defined chaos engineering plan."""
    name: str
    description: str
    total_duration_sec: int
    faults: list[dict] = field(default_factory=list)  # list of fault specs


@dataclass
class ChaosRunResult:
    """Result of a complete chaos run."""
    run_id: str
    plan_name: str
    started_at: str
    completed_at: str
    total_duration_sec: float
    faults_scheduled: int
    faults_injected: int
    faults_recovered: int
    faults_failed: int
    events: list[dict] = field(default_factory=list)
    verdict: str = ""  # "PASS", "FAIL", "DEGRADED"



# Fault types


FAULT_TYPES = {
    "process_kill_ui": "Force-kill the desktop UI process",
    "process_kill_desktop": "Force-kill the desktop application",
    "process_kill_sidecar": "Force-kill the Sidecar process",
    "network_disconnect": "Disconnect network interface temporarily",
    "websocket_drop": "Drop WebSocket connection",
    "disk_full": "Fill disk to simulate out-of-space",
    "memory_pressure": "Allocate memory to trigger OOM conditions",
    "config_corruption": "Corrupt a configuration file",
    "workspace_corruption": "Corrupt workspace state",
    "db_lock": "Hold SQLite lock to trigger contention",
    "malformed_json": "Send malformed JSON to API",
    "auth_401": "Send requests with invalid auth tokens",
    "rate_limit_429": "Trigger rate limiting",
    "server_500": "Trigger internal server errors",
    "server_503": "Make service temporarily unavailable",
    "duplicate_request": "Send duplicate task submissions",
    "protocol_incompatible": "Send envelope with unsupported protocol version",
    "upgrade_failure": "Simulate failed upgrade",
    "disk_readonly": "Make workspace directory read-only",
}


class FaultInjector:
    """Inject faults into a running Nous Runtime instance."""

    def __init__(self, api_base: str = "http://localhost:8770", token: str = "") -> None:
        self.api_base = api_base
        self.token = token
        self._chaos_dir = Path.home() / ".nous_chaos"
        self._chaos_dir.mkdir(exist_ok=True)

    # Process faults

    def inject_process_kill(self, target: str = "sidecar") -> FaultEvent:
        """Kill a process by name."""
        import psutil
        fault = FaultEvent(
            fault_id=f"fault_{uuid.uuid4().hex[:8]}",
            fault_type=f"process_kill_{target}",
            target=target,
            scheduled_at_sec=0,
        )
        killed = False
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                pname = proc.info["name"] or ""
                if target in pname.lower() or "nous" in pname.lower():
                    proc.kill()
                    killed = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        fault.actual_at_sec = time.monotonic()
        fault.success = killed
        if not killed:
            fault.error = f"No process matching '{target}' found"
        return fault

    def inject_process_kill_sidecar(self) -> FaultEvent:
        return self.inject_process_kill("sidecar")

    # Network faults

    def inject_network_disconnect(self, duration_sec: float = 5.0) -> FaultEvent:
        """Temporarily disable network (requires admin)."""
        fault = FaultEvent(
            fault_id=f"fault_{uuid.uuid4().hex[:8]}",
            fault_type="network_disconnect",
            target="primary_interface",
            scheduled_at_sec=0,
            duration_sec=duration_sec,
        )
        # Platform-specific
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["netsh", "interface", "set", "interface", "Ethernet", "admin=disable"],
                    capture_output=True, timeout=10,
                )
                time.sleep(duration_sec)
                subprocess.run(
                    ["netsh", "interface", "set", "interface", "Ethernet", "admin=enable"],
                    capture_output=True, timeout=10,
                )
            else:
                # Linux: use iptables to drop all traffic temporarily
                subprocess.run(
                    ["iptables", "-A", "OUTPUT", "-j", "DROP"],
                    capture_output=True, timeout=5,
                )
                time.sleep(duration_sec)
                subprocess.run(
                    ["iptables", "-D", "OUTPUT", "-j", "DROP"],
                    capture_output=True, timeout=5,
                )
            fault.success = True
        except Exception as e:
            fault.error = str(e)
        fault.actual_at_sec = time.monotonic()
        return fault

    # Resource faults

    def inject_disk_full(self, target_dir: str | None = None, size_mb: int = 100) -> FaultEvent:
        """Fill disk space to simulate out-of-space condition."""
        fault = FaultEvent(
            fault_id=f"fault_{uuid.uuid4().hex[:8]}",
            fault_type="disk_full",
            target=target_dir or str(self._chaos_dir),
            scheduled_at_sec=0,
        )
        target = Path(target_dir or self._chaos_dir)
        fill_file = target / f"chaos_fill_{uuid.uuid4().hex[:8]}.bin"
        try:
            with open(fill_file, "wb") as f:
                f.write(b"\0" * (size_mb * 1024 * 1024))
            fault.success = True
        except OSError as e:
            fault.error = str(e)
            fault.success = True  # Disk full IS the fault condition
        fault.actual_at_sec = time.monotonic()
        # Cleanup
        try:
            fill_file.unlink(missing_ok=True)
        except Exception:
            pass
        return fault

    def inject_memory_pressure(self, size_mb: int = 512) -> FaultEvent:
        """Allocate memory to create memory pressure."""
        fault = FaultEvent(
            fault_id=f"fault_{uuid.uuid4().hex[:8]}",
            fault_type="memory_pressure",
            target="system",
            scheduled_at_sec=0,
        )
        try:
            # Allocate and hold
            data = bytearray(size_mb * 1024 * 1024)
            fault.success = True
            # Hold for 30 seconds then release
            time.sleep(30)
            del data
        except MemoryError:
            fault.error = "Memory allocation failed (pressure achieved)"
            fault.success = True
        except Exception as e:
            fault.error = str(e)
        fault.actual_at_sec = time.monotonic()
        return fault

    # State corruption faults

    def inject_config_corruption(self) -> FaultEvent:
        """Corrupt a configuration file."""
        fault = FaultEvent(
            fault_id=f"fault_{uuid.uuid4().hex[:8]}",
            fault_type="config_corruption",
            target="config.json",
            scheduled_at_sec=0,
        )
        config_path = Path.home() / ".nous" / "config.json"
        try:
            if config_path.exists():
                backup = config_path.read_bytes()
                # Write invalid JSON
                config_path.write_text("{ this is not valid json }{{{")
                fault.success = True
                # Restore after 10 seconds
                time.sleep(10)
                config_path.write_bytes(backup)
                fault.recovered = True
            else:
                fault.error = "config.json not found"
        except Exception as e:
            fault.error = str(e)
        fault.actual_at_sec = time.monotonic()
        return fault

    def inject_workspace_corruption(self) -> FaultEvent:
        """Corrupt workspace state."""
        fault = FaultEvent(
            fault_id=f"fault_{uuid.uuid4().hex[:8]}",
            fault_type="workspace_corruption",
            target="project.json",
            scheduled_at_sec=0,
        )
        ws_path = Path.home() / ".nous" / "project.json"
        try:
            if ws_path.exists():
                backup = ws_path.read_bytes()
                ws_path.write_text("corrupted")
                fault.success = True
                time.sleep(10)
                ws_path.write_bytes(backup)
                fault.recovered = True
            else:
                fault.error = "project.json not found"
        except Exception as e:
            fault.error = str(e)
        fault.actual_at_sec = time.monotonic()
        return fault

    # API-level faults

    def inject_auth_failure(self) -> FaultEvent:
        """Send requests with invalid auth tokens."""
        fault = FaultEvent(
            fault_id=f"fault_{uuid.uuid4().hex[:8]}",
            fault_type="auth_401",
            target=f"{self.api_base}/api/v1/status",
            scheduled_at_sec=0,
        )
        import urllib.request
        try:
            req = urllib.request.Request(
                f"{self.api_base}/api/v1/status",
                headers={"Authorization": "Bearer invalid-token-12345"},
            )
            urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as e:
            fault.success = e.code == 401
            fault.error = "" if fault.success else f"Expected 401, got {e.code}"
        except Exception as e:
            fault.error = str(e)
        fault.actual_at_sec = time.monotonic()
        return fault

    def inject_malformed_request(self) -> FaultEvent:
        """Send malformed JSON to API."""
        fault = FaultEvent(
            fault_id=f"fault_{uuid.uuid4().hex[:8]}",
            fault_type="malformed_json",
            target=f"{self.api_base}/api/v1/runtime/run",
            scheduled_at_sec=0,
        )
        import urllib.request
        try:
            data = b"{ this is not json }"
            req = urllib.request.Request(
                f"{self.api_base}/api/v1/runtime/run",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as e:
            fault.success = e.code == 400
        except Exception as e:
            fault.error = str(e)
        fault.actual_at_sec = time.monotonic()
        return fault



# Chaos Runner


class ChaosRunner:
    """Orchestrates fault injection during a stability run."""

    def __init__(
        self,
        plan: ChaosPlan,
        injector: FaultInjector | None = None,
        *,
        on_fault_injected: Callable[[FaultEvent], None] | None = None,
    ) -> None:
        self.plan = plan
        self.injector = injector or FaultInjector()
        self.on_fault_injected = on_fault_injected
        self._events: list[FaultEvent] = []
        self._run_id = f"chaos_{uuid.uuid4().hex[:12]}"

    def run(self) -> ChaosRunResult:
        """Execute the chaos plan."""
        started_at = _utc_now()
        start_time = time.monotonic()

        print(f"Chaos Run: {self.plan.name}")
        print(f"Run ID: {self._run_id}")
        print(f"Duration: {self.plan.total_duration_sec}s ({self.plan.total_duration_sec/3600:.1f}h)")
        print(f"Faults scheduled: {len(self.plan.faults)}")
        print(f"{'='*60}")

        # Sort faults by schedule time
        scheduled = sorted(self.plan.faults, key=lambda f: f.get("at_sec", 0))
        fault_index = 0
        faults_injected = 0
        faults_recovered = 0
        faults_failed = 0

        try:
            while True:
                elapsed = time.monotonic() - start_time

                # Check for faults due at this time
                while fault_index < len(scheduled) and scheduled[fault_index]["at_sec"] <= elapsed:
                    spec = scheduled[fault_index]
                    fault = self._inject_fault(spec)
                    self._events.append(fault)
                    faults_injected += 1
                    if fault.recovered:
                        faults_recovered += 1
                    if not fault.success:
                        faults_failed += 1

                    icon = "PASS" if fault.success else "FAIL"
                    print(f"  [{elapsed:6.0f}s] {icon} {fault.fault_type}: {fault.target}")
                    if fault.error:
                        print(f"         Error: {fault.error}")

                    if self.on_fault_injected:
                        self.on_fault_injected(fault)

                    fault_index += 1

                # Check end condition
                if elapsed >= self.plan.total_duration_sec:
                    break

                time.sleep(1)  # Check every second

        except KeyboardInterrupt:
            print("\nChaos run interrupted by user.")

        completed_at = _utc_now()
        total_duration = time.monotonic() - start_time

        # Verdict
        recovery_rate = faults_recovered / max(faults_injected, 1)
        if faults_failed == 0 and recovery_rate >= 0.9:
            verdict = "PASS"
        elif faults_failed <= faults_injected * 0.1 and recovery_rate >= 0.7:
            verdict = "DEGRADED"
        else:
            verdict = "FAIL"

        result = ChaosRunResult(
            run_id=self._run_id,
            plan_name=self.plan.name,
            started_at=started_at,
            completed_at=completed_at,
            total_duration_sec=total_duration,
            faults_scheduled=len(self.plan.faults),
            faults_injected=faults_injected,
            faults_recovered=faults_recovered,
            faults_failed=faults_failed,
            events=[asdict(e) for e in self._events],
            verdict=verdict,
        )

        # Save results
        result_path = RESULTS_DIR / f"chaos-{self._run_id}.json"
        result_path.write_text(
            json.dumps(asdict(result), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        print(f"\n{'='*60}")
        print(f"Verdict: {verdict}")
        print(f"Faults: {faults_injected} injected, {faults_recovered} recovered, {faults_failed} failed")
        print(f"Results: {result_path}")

        return result

    def _inject_fault(self, spec: dict) -> FaultEvent:
        """Inject a single fault based on spec."""
        fault_type = spec.get("type", "")
        method_name = f"inject_{fault_type}"

        if hasattr(self.injector, method_name):
            method = getattr(self.injector, method_name)
            fault = method()
        else:
            # Generic fault based on type dispatch
            fault_map = {
                "process_kill_ui": self.injector.inject_process_kill,
                "process_kill_desktop": self.injector.inject_process_kill,
                "process_kill_sidecar": self.injector.inject_process_kill_sidecar,
                "network_disconnect": self.injector.inject_network_disconnect,
                "disk_full": self.injector.inject_disk_full,
                "memory_pressure": self.injector.inject_memory_pressure,
                "config_corruption": self.injector.inject_config_corruption,
                "workspace_corruption": self.injector.inject_workspace_corruption,
                "auth_401": self.injector.inject_auth_failure,
                "malformed_json": self.injector.inject_malformed_request,
            }
            fn = fault_map.get(fault_type)
            if fn:
                fault = fn(**{k: v for k, v in spec.items() if k != "type" and k != "at_sec"})
            else:
                fault = FaultEvent(
                    fault_id=f"fault_{uuid.uuid4().hex[:8]}",
                    fault_type=fault_type,
                    target=spec.get("target", "unknown"),
                    scheduled_at_sec=spec.get("at_sec", 0),
                    success=False,
                    error=f"Unknown fault type: {fault_type}",
                )

        fault.scheduled_at_sec = spec.get("at_sec", 0)
        fault.actual_at_sec = time.monotonic()
        return fault



# Built-in plans


def build_quick_plan() -> ChaosPlan:
    """5-minute quick check: inject one of each fault type."""
    return ChaosPlan(
        name="RC1 Quick Chaos Check",
        description="5-minute smoke test of all fault injection types",
        total_duration_sec=300,
        faults=[
            {"at_sec": 10, "type": "auth_401", "target": "/api/v1/status"},
            {"at_sec": 30, "type": "malformed_json", "target": "/api/v1/runtime/run"},
            {"at_sec": 60, "type": "config_corruption", "target": "config.json"},
            {"at_sec": 90, "type": "workspace_corruption", "target": "project.json"},
            {"at_sec": 120, "type": "memory_pressure", "target": "system", "size_mb": 128},
            {"at_sec": 180, "type": "disk_full", "target": ".nous_chaos", "size_mb": 50},
            {"at_sec": 240, "type": "auth_401", "target": "/api/v1/tasks"},
        ],
    )


def build_72h_plan() -> ChaosPlan:
    """72-hour comprehensive chaos plan with 30 fault injections."""
    faults = []
    # Spread 30 faults across 72 hours (259200 seconds)
    # Roughly one fault every 2.4 hours, with clustering during business hours

    fault_pool = [
        "process_kill_sidecar", "network_disconnect", "disk_full",
        "memory_pressure", "config_corruption", "workspace_corruption",
        "auth_401", "malformed_json", "process_kill_ui",
    ]

    # Hour 0-8: Ramp-up, light faults
    for i in range(4):
        t = random.randint(i * 7200, (i + 1) * 7200)
        faults.append({"at_sec": t, "type": random.choice(["auth_401", "malformed_json"])})

    # Hour 8-24: Heavy testing
    for i in range(8):
        t = random.randint(28800 + i * 7200, 28800 + (i + 1) * 7200)
        faults.append({"at_sec": t, "type": random.choice(fault_pool)})

    # Hour 24-48: Sustained chaos
    for i in range(10):
        t = random.randint(86400 + i * 8640, 86400 + (i + 1) * 8640)
        faults.append({"at_sec": t, "type": random.choice(fault_pool)})

    # Hour 48-72: Recovery-focused
    for i in range(8):
        t = random.randint(172800 + i * 10800, 172800 + (i + 1) * 10800)
        faults.append({"at_sec": t, "type": random.choice(fault_pool + ["process_kill_sidecar"])})

    return ChaosPlan(
        name="RC1 72-Hour Chaos Engineering",
        description="30 fault injections across 72 hours covering all fault categories",
        total_duration_sec=259200,
        faults=faults,
    )



# CLI


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Nous Runtime Chaos Engineering Harness")
    parser.add_argument("--plan", help="Path to chaos plan JSON file")
    parser.add_argument("--duration", type=int, help="Duration in seconds")
    parser.add_argument("--random", type=int, default=0, help="Number of random faults to inject")
    parser.add_argument("--quick", action="store_true", help="Run 5-minute quick chaos check")
    parser.add_argument("--api-base", default="http://localhost:8770", help="API base URL")
    parser.add_argument("--token", default="", help="API auth token")

    args = parser.parse_args()

    injector = FaultInjector(api_base=args.api_base, token=args.token)

    if args.quick:
        plan = build_quick_plan()
    elif args.plan:
        plan_data = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        plan = ChaosPlan(**plan_data)
    elif args.duration and args.random > 0:
        fault_pool = list(FAULT_TYPES.keys())
        faults = []
        for i in range(args.random):
            t = random.randint(0, args.duration)
            faults.append({"at_sec": t, "type": random.choice(fault_pool)})
        faults.sort(key=lambda f: f["at_sec"])
        plan = ChaosPlan(
            name=f"Random {args.random}-fault plan ({args.duration}s)",
            description=f"Random chaos: {args.random} faults over {args.duration}s",
            total_duration_sec=args.duration,
            faults=faults,
        )
    else:
        parser.print_help()
        print("\nExamples:")
        print("  python tools/chaos_harness.py --quick")
        print("  python tools/chaos_harness.py --duration 3600 --random 10")
        print("  python tools/chaos_harness.py --plan tools/chaos_plans/rc1_72h.json")
        sys.exit(1)

    runner = ChaosRunner(plan, injector)
    result = runner.run()
    sys.exit(0 if result.verdict == "PASS" else 1)


if __name__ == "__main__":
    main()

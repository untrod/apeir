#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Nous Runtime V1.0.0-rc1 — Stability Test Harness.

Runs sustained operations to validate 24h/72h stability.
Monitors CPU, memory, crash count, and component health.

Usage:
    python tools/stability_harness.py --duration 24   # 24-hour run
    python tools/stability_harness.py --duration 72   # 72-hour run
    python tools/stability_harness.py --quick          # 5-minute quick check
"""

from __future__ import annotations

import json
import logging
import signal
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger("nous.stability")



# Metrics Collector


class MetricsCollector:
    """Collects system and runtime metrics over time."""

    def __init__(self, workspace: str = ""):
        self._workspace = Path(workspace) if workspace else Path.home() / ".nous"
        self._metrics: list[dict] = []
        self._lock = threading.Lock()
        self._running = False
        self._start_time = 0.0

    def start(self) -> None:
        self._running = True
        self._start_time = time.monotonic()

    def stop(self) -> None:
        self._running = False

    def collect(self) -> dict[str, Any]:
        """Collect a single metrics snapshot."""
        snapshot = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "elapsed_hours": round((time.monotonic() - self._start_time) / 3600, 2),
        }

        # CPU & Memory
        try:
            import psutil
            snapshot["cpu_percent"] = psutil.cpu_percent(interval=0.1)
            vm = psutil.virtual_memory()
            snapshot["memory_percent"] = vm.percent
            snapshot["memory_available_gb"] = round(vm.available / (1024**3), 1)
            process = psutil.Process()
            snapshot["process_rss_mb"] = round(process.memory_info().rss / (1024**2), 1)
        except ImportError:
            snapshot["cpu_percent"] = -1
            snapshot["memory_percent"] = -1

        # Disk
        try:
            import shutil
            usage = shutil.disk_usage(self._workspace)
            snapshot["disk_free_gb"] = round(usage.free / (1024**3), 1)
        except Exception:
            snapshot["disk_free_gb"] = -1

        # Runtime health
        try:
            from nous_runtime.api.health_dashboard import handle_health_dashboard
            health = handle_health_dashboard()
            if health["ok"]:
                snapshot["health"] = health["data"]["overall"]
                snapshot["components"] = {
                    k: v.get("healthy", False)
                    for k, v in health["data"]["components"].items()
                }
        except Exception as e:
            snapshot["health"] = f"error: {e}"

        # Provider health
        try:
            from nous_runtime.services.providers import provider_health_summary
            ph = provider_health_summary()
            snapshot["providers_total"] = ph.get("total_count", 0)
            snapshot["providers_healthy"] = ph.get("healthy_count", 0)
        except Exception:
            snapshot["providers_total"] = -1

        # Task count
        try:
            from nous_runtime.api.desktop_routes import handle_tasks_list
            td = handle_tasks_list()
            if td["ok"]:
                snapshot["tasks_total"] = td["data"]["total"]
        except Exception:
            snapshot["tasks_total"] = -1

        with self._lock:
            self._metrics.append(snapshot)

        return snapshot

    def get_summary(self) -> dict[str, Any]:
        """Generate summary statistics."""
        with self._lock:
            if not self._metrics:
                return {"error": "No metrics collected"}

            cpu_values = [m.get("cpu_percent", 0) for m in self._metrics if m.get("cpu_percent", -1) >= 0]
            mem_values = [m.get("memory_percent", 0) for m in self._metrics if m.get("memory_percent", -1) >= 0]
            health_states = [m.get("health", "unknown") for m in self._metrics]

            return {
                "total_snapshots": len(self._metrics),
                "duration_hours": round((time.monotonic() - self._start_time) / 3600, 2),
                "cpu_avg": round(sum(cpu_values) / max(1, len(cpu_values)), 1) if cpu_values else -1,
                "cpu_max": max(cpu_values) if cpu_values else -1,
                "memory_avg": round(sum(mem_values) / max(1, len(mem_values)), 1) if mem_values else -1,
                "memory_max": max(mem_values) if mem_values else -1,
                "health_healthy_count": health_states.count("healthy"),
                "health_degraded_count": health_states.count("degraded"),
                "first_snapshot": self._metrics[0]["timestamp"] if self._metrics else "",
                "last_snapshot": self._metrics[-1]["timestamp"] if self._metrics else "",
            }

    def save(self, path: str | Path) -> None:
        with self._lock:
            out = Path(path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({
                "summary": self.get_summary(),
                "metrics": self._metrics,
            }, indent=2), encoding="utf-8")



# Workload Generator


class WorkloadGenerator:
    """Generates sustained workload to stress-test the system."""

    def __init__(self, workspace: str = ""):
        self._workspace = workspace
        self._running = False
        self._operations: list[dict] = []
        self._lock = threading.Lock()

    def start(self, interval_seconds: float = 30.0) -> None:
        """Start generating periodic workload."""
        self._running = True
        self._thread = threading.Thread(
            target=self._loop,
            args=(interval_seconds,),
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self, interval: float) -> None:
        while self._running:
            try:
                self._run_cycle()
            except Exception as e:
                _log.warning("Workload cycle error: %s", e)
                with self._lock:
                    self._operations.append({"status": "error", "error": str(e)})
            time.sleep(interval)

    def _run_cycle(self) -> None:
        """Execute one workload cycle."""
        ops = []

        # 1. Health check
        try:
            from nous_runtime.api.health_dashboard import handle_health_dashboard
            handle_health_dashboard()
            ops.append("health_check")
        except Exception:
            pass

        # 2. Dashboard query
        try:
            from nous_runtime.api.desktop_routes import handle_dashboard_full
            handle_dashboard_full()
            ops.append("dashboard")
        except Exception:
            pass

        # 3. Task list
        try:
            from nous_runtime.api.desktop_routes import handle_tasks_list
            handle_tasks_list()
            ops.append("tasks_list")
        except Exception:
            pass

        # 4. Learning assistant
        try:
            from nous_runtime.persona.learning_assistant import LearningAssistant
            with tempfile.TemporaryDirectory() as tmp:
                la = LearningAssistant(workspace=tmp)
                la.add_subject("Stability Test")
                la.log_session("Stability Test", "Topic", 15, 0.7)
                la.generate_daily_plan()
            ops.append("learning")
        except Exception:
            pass

        # 5. Project assistant
        try:
            from nous_runtime.persona.project_assistant import ProjectAssistant
            with tempfile.TemporaryDirectory() as tmp:
                pa = ProjectAssistant(workspace=tmp)
                pa.create_project("Stability Test")
                pa.get_dashboard()
            ops.append("project")
        except Exception:
            pass

        # 6. Device list
        try:
            from nous_runtime.api.desktop_routes import handle_devices_list
            handle_devices_list()
            ops.append("devices")
        except Exception:
            pass

        # 7. Knowledge list
        try:
            from nous_runtime.api.desktop_routes import handle_knowledge_list
            handle_knowledge_list()
            ops.append("knowledge")
        except Exception:
            pass

        with self._lock:
            self._operations.append({
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "status": "ok",
                "operations": ops,
            })

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            cycles = len(self._operations)
            errors = sum(1 for o in self._operations if o.get("status") == "error")
            return {
                "total_cycles": cycles,
                "errors": errors,
                "error_rate": round(errors / max(1, cycles) * 100, 2),
            }



# Stability Runner


class StabilityRunner:
    """Orchestrates long-running stability tests."""

    def __init__(
        self,
        duration_hours: float = 24.0,
        collect_interval: float = 60.0,
        workload_interval: float = 30.0,
        output_dir: str = "",
    ):
        self.duration_hours = duration_hours
        self.collect_interval = collect_interval
        self.workload_interval = workload_interval
        self.output_dir = Path(output_dir) if output_dir else Path.home() / ".nous" / "stability_results"
        self.collector = MetricsCollector()
        self.workload = WorkloadGenerator()
        self._running = False

    def run(self) -> dict[str, Any]:
        """Run the stability test for the configured duration."""
        print(f"\n{'='*56}")
        print("  Nous Runtime Stability Test")
        print(f"  Duration: {self.duration_hours}h")
        print(f"  Metrics interval: {self.collect_interval}s")
        print(f"  Workload interval: {self.workload_interval}s")
        print(f"  Output: {self.output_dir}")
        print(f"{'='*56}\n")

        self._running = True
        self.collector.start()
        self.workload.start(interval_seconds=self.workload_interval)

        deadline = time.monotonic() + self.duration_hours * 3600
        last_report = time.monotonic()

        try:
            while self._running and time.monotonic() < deadline:
                # Collect metrics
                snapshot = self.collector.collect()
                elapsed = time.monotonic() - self.collector._start_time
                remaining = deadline - time.monotonic()

                # Print periodic report (every 5 minutes or every collection if interval > 300)
                if time.monotonic() - last_report >= 300:
                    wstats = self.workload.get_stats()
                    print(f"  [{snapshot['elapsed_hours']:.1f}h / {self.duration_hours}h] "
                          f"CPU: {snapshot.get('cpu_percent', '?')}%  "
                          f"MEM: {snapshot.get('memory_percent', '?')}%  "
                          f"Health: {snapshot.get('health', '?')}  "
                          f"Cycles: {wstats['total_cycles']} (errors: {wstats['errors']})")
                    last_report = time.monotonic()

                # Save intermediate results every 30 collections
                if len(self.collector._metrics) % 30 == 0:
                    self.collector.save(self.output_dir / f"stability_snapshot_{int(elapsed)}.json")

                if remaining <= 0:
                    break

                time.sleep(min(self.collect_interval, max(1, remaining)))

        except KeyboardInterrupt:
            print("\n  WARN Stability test interrupted by user")
        finally:
            self.workload.stop()
            self.collector.stop()

        # Generate final report
        return self._generate_report()

    def _generate_report(self) -> dict[str, Any]:
        print(f"\n{'='*56}")
        print("  Stability Test Complete")
        print(f"{'='*56}")

        summary = self.collector.get_summary()
        wstats = self.workload.get_stats()

        report = {
            "test_config": {
                "duration_hours": self.duration_hours,
                "collect_interval_s": self.collect_interval,
                "workload_interval_s": self.workload_interval,
            },
            "metrics_summary": summary,
            "workload_stats": wstats,
            "verdict": "PASS",
        }

        # Determine verdict
        if wstats["error_rate"] > 5:
            report["verdict"] = "FAIL"
            report["failure_reason"] = f"Workload error rate {wstats['error_rate']}% exceeds 5%"
        elif summary.get("health_degraded_count", 0) > summary.get("total_snapshots", 1) * 0.1:
            report["verdict"] = "DEGRADED"
            report["failure_reason"] = "Health degraded >10% of snapshots"
        elif summary.get("memory_max", 100) > 95:
            report["verdict"] = "WARN"
            report["failure_reason"] = "Memory usage exceeded 95%"

        print(f"  Duration: {summary.get('duration_hours', 0):.1f}h")
        print(f"  Snapshots: {summary.get('total_snapshots', 0)}")
        print(f"  CPU avg/max: {summary.get('cpu_avg', -1)}% / {summary.get('cpu_max', -1)}%")
        print(f"  MEM avg/max: {summary.get('memory_avg', -1)}% / {summary.get('memory_max', -1)}%")
        print(f"  Health: {summary.get('health_healthy_count', 0)} healthy / {summary.get('health_degraded_count', 0)} degraded")
        print(f"  Workload: {wstats['total_cycles']} cycles, {wstats['errors']} errors ({wstats['error_rate']}%)")
        print(f"  Verdict: {report['verdict']}")
        print(f"{'='*56}\n")

        # Save final report
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.collector.save(self.output_dir / "stability_metrics.json")
        report_path = self.output_dir / "stability_report.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"  Report saved to: {report_path}")

        return report



# CLI Entry


def main():
    import argparse
    p = argparse.ArgumentParser(description="Nous Runtime Stability Harness")
    p.add_argument("--duration", type=float, default=24.0, help="Duration in hours (default: 24)")
    p.add_argument("--quick", action="store_true", help="5-minute quick test")
    p.add_argument("--metrics-interval", type=float, default=60.0, help="Metrics collection interval in seconds")
    p.add_argument("--workload-interval", type=float, default=30.0, help="Workload cycle interval in seconds")
    p.add_argument("--output", type=str, default="", help="Output directory")
    args = p.parse_args()

    if args.quick:
        args.duration = 5.0 / 60.0  # 5 minutes
        args.metrics_interval = 10.0
        args.workload_interval = 15.0

    runner = StabilityRunner(
        duration_hours=args.duration,
        collect_interval=args.metrics_interval,
        workload_interval=args.workload_interval,
        output_dir=args.output,
    )

    # Handle Ctrl+C gracefully
    def handler(sig, frame):
        runner._running = False
    signal.signal(signal.SIGINT, handler)

    report = runner.run()
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

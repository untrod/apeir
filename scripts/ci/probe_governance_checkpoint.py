"""Measure the existing SQLite owner's last-close work; never change production policy."""

from __future__ import annotations

import argparse
import hashlib
import importlib
from contextlib import contextmanager
import json
import os
from pathlib import Path
import platform
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nous_runtime.governance import store  # noqa: E402


def supported() -> bool:
    return hasattr(sqlite3.Connection, "setconfig") and hasattr(
        sqlite3, "SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE"
    )


@contextmanager
def connection_mode(retain_wal: bool):
    original = store._db_connect

    @contextmanager
    def experimental(path, readonly=False):
        with original(path, readonly=readonly) as connection:
            connection.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, retain_wal)
            assert (
                connection.getconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE)
                is retain_wal
            )
            yield connection

    store._db_connect = experimental
    try:
        yield
    finally:
        store._db_connect = original


def quantiles(values):
    ordered = sorted(values)

    def at(percent):
        index = (len(ordered) - 1) * percent
        low = int(index)
        high = min(low + 1, len(ordered) - 1)
        return ordered[low] + (ordered[high] - ordered[low]) * (index - low)

    return {"p50_ms": statistics.median(values), "p95_ms": at(0.95), "p99_ms": at(0.99)}


def probe():
    count = 101
    samples = {name: [] for name in ("legacy", "retained-wal")}
    cpu = {name: [] for name in samples}
    phases = {
        name: {key: [] for key in ("connect", "configure", "commit", "close")}
        for name in samples
    }
    wal = {name: [] for name in samples}
    active = None
    original_phase = store._sqlite_phase

    @contextmanager
    def observed(phase, readonly):
        started = time.perf_counter()
        try:
            with original_phase(phase, readonly):
                yield
        finally:
            if active is not None and phase in phases[active]:
                phases[active][phase].append((time.perf_counter() - started) * 1000)

    store._sqlite_phase = observed
    try:
        with tempfile.TemporaryDirectory(prefix="apeir-checkpoint-probe-") as directory:
            owners = {}
            for name in samples:
                with connection_mode(name == "retained-wal"):
                    owners[name] = store.GovernanceStore(Path(directory) / name)
            for index in range(count):
                order = (
                    ("legacy", "retained-wal")
                    if index % 2 == 0
                    else ("retained-wal", "legacy")
                )
                for name in order:
                    owner = owners[name]
                    active = name
                    started_cpu = time.process_time()
                    started = time.perf_counter()
                    with (
                        connection_mode(name == "retained-wal"),
                        owner.operation_transaction() as db,
                    ):
                        assert db.execute("PRAGMA synchronous").fetchone()[0] == 2
                        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
                        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
                        assert (
                            db.execute("PRAGMA wal_autocheckpoint").fetchone()[0]
                            == 1000
                        )
                        owner.append_operation_audit(
                            db,
                            "checkpoint.probe",
                            {"sample": index, "source": "fake-only"},
                        )
                    samples[name].append((time.perf_counter() - started) * 1000)
                    cpu[name].append((time.process_time() - started_cpu) * 1000)
                    active = None
                    wal[name].append(Path(owner.db_path + "-wal").exists())
            for name, owner in owners.items():
                with (
                    connection_mode(name == "retained-wal"),
                    store._db_connect(owner.db_path, readonly=True) as db,
                ):
                    assert (
                        db.execute("SELECT COUNT(*) FROM governance_audit").fetchone()[
                            0
                        ]
                        == count
                    )
                    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            return {
                "samples_per_path": count,
                "ordering": "alternating paired order; fixed payload",
                "scope": "existing Governance audit transaction; excludes schema initialization and HTTP",
                "tail_limit": "descriptive interpolated quantiles; this sample does not establish a tail SLA",
                "cpu_measurement": "process_time deltas; Windows accounting may be coarse, so a zero delta is not zero workload",
                "wall": {name: quantiles(values) for name, values in samples.items()},
                "cpu": {name: quantiles(values) for name, values in cpu.items()},
                "phases": {
                    name: {phase: quantiles(values) for phase, values in rows.items()}
                    for name, rows in phases.items()
                },
                "wal_present_after_every_close": {
                    name: all(values) for name, values in wal.items()
                },
                "integrity_and_all_records": "PASS",
                "raw_wall_ms": samples,
                "raw_cpu_ms": cpu,
                "raw_phase_ms": phases,
            }
    finally:
        store._sqlite_phase = original_phase


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--exercise-mcp", action="store_true")
    parser.add_argument("--exercise-only", choices=("legacy", "retained-wal"))
    parser.add_argument("--runtime-schema", action="store_true")
    arguments = parser.parse_args()
    if arguments.runtime_schema:
        if (
            arguments.exercise_mcp
            or arguments.exercise_only
            or arguments.report is None
        ):
            parser.error("--runtime-schema requires only --report")
        report = {
            "source_revision": os.environ.get(
                "GITHUB_SHA", "local-uncommitted-diagnostic"
            ),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
            "qualification": "DIAGNOSTIC_ONLY; not an HTTP deadline, model or native-install qualification",
            "measurement": probe_runtime_schemas(),
        }
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, indent=2))
        return 0
    if not supported():
        raise SystemExit("SQLite checkpoint experiment unavailable on this interpreter")
    if arguments.exercise_only:
        import pytest

        with connection_mode(arguments.exercise_only == "retained-wal"):
            return pytest.main(
                [
                    "-q",
                    str(ROOT / "tests/extensions/test_runtime_mcp_server.py"),
                    "--tb=short",
                    "--timeout=60",
                    "-rA",
                ]
            )
    if arguments.report is None:
        parser.error("--report is required")
    report = {
        "source_revision": os.environ.get("GITHUB_SHA", "local-uncommitted-diagnostic"),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "production_policy_changed": False,
        "qualification": "DIAGNOSTIC_ONLY; not Core, native install or physical acceptance",
        "measurement": probe(),
    }
    outcomes = {}
    if arguments.exercise_mcp:
        for mode in ("legacy", "retained-wal"):
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--exercise-only",
                    mode,
                ],
                cwd=ROOT,
                check=False,
            )
            outcomes[mode] = result.returncode
    report["original_mcp_regression_exit_codes"] = outcomes
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 1 if any(outcomes.values()) else 0


def probe_runtime_schemas():
    """Paired cold initialization through the two existing post-model owners.

    The legacy arm removes only the newly added BEGIN from the same schema SQL.
    No production database, pool, journal policy or HTTP limit is changed.
    """
    results = {}
    for module_name, class_name in (
        ("nous_runtime.evaluation.history", "EvaluationHistory"),
        ("nous_runtime.experience.store", "ExperienceStore"),
    ):
        owner = importlib.import_module(module_name)
        original_connect = owner._db_connect
        wall = {"legacy": [], "atomic": []}
        cpu = {"legacy": [], "atomic": []}
        ddl_states = {"legacy": [], "atomic": []}
        schema_digests = set()

        class LegacySchema:
            def __init__(self, connection):
                self.connection = connection

            def executescript(self, sql):
                prefix = "BEGIN IMMEDIATE;"
                if not sql.startswith(prefix):
                    raise RuntimeError("Candidate schema has no explicit BEGIN")
                schema_digests.add(
                    hashlib.sha256(sql[len(prefix) :].encode()).hexdigest()
                )
                return self.connection.executescript(sql[len(prefix) :])

        @contextmanager
        def measured(path, readonly=False):
            with original_connect(path, readonly=readonly) as connection:
                if readonly:
                    yield connection
                    return

                def trace(sql):
                    if sql.strip().upper().startswith("CREATE "):
                        ddl_states[mode].append(connection.in_transaction)

                connection.set_trace_callback(trace)
                yield LegacySchema(connection) if mode == "legacy" else connection

        with tempfile.TemporaryDirectory(prefix="apeir-runtime-schema-") as directory:
            try:
                owner._db_connect = measured
                for index in range(21):
                    order = (
                        ("legacy", "atomic") if index % 2 == 0 else ("atomic", "legacy")
                    )
                    for mode in order:
                        path = Path(directory) / f"{mode}-{index}"
                        started_cpu, started = time.process_time(), time.perf_counter()
                        instance = getattr(owner, class_name)(path)
                        wall[mode].append((time.perf_counter() - started) * 1000)
                        cpu[mode].append((time.process_time() - started_cpu) * 1000)
                        with original_connect(
                            instance.db_path, readonly=True
                        ) as connection:
                            assert (
                                connection.execute("PRAGMA journal_mode").fetchone()[0]
                                == "wal"
                            )
                            assert (
                                connection.execute("PRAGMA synchronous").fetchone()[0]
                                == 2
                            )
                            assert (
                                connection.execute("PRAGMA foreign_keys").fetchone()[0]
                                == 1
                            )
                            assert (
                                connection.execute("PRAGMA integrity_check").fetchone()[
                                    0
                                ]
                                == "ok"
                            )
            finally:
                owner._db_connect = original_connect
        assert len(schema_digests) == 1
        assert ddl_states["legacy"] and not any(ddl_states["legacy"])
        assert ddl_states["atomic"] and all(ddl_states["atomic"])
        results[class_name] = {
            "samples_per_arm": 21,
            "ordering": "alternating paired order; fresh database per sample",
            "legacy_schema_sql_sha256": next(iter(schema_digests)),
            "wall_ms": {name: quantiles(values) for name, values in wall.items()},
            "cpu_ms": {name: quantiles(values) for name, values in cpu.items()},
            "raw_wall_ms": wall,
            "raw_cpu_ms": cpu,
            "wal_full_sync_foreign_keys_and_integrity": "PASS",
            "legacy_ddl_without_explicit_transaction": True,
            "candidate_ddl_in_single_transaction": True,
        }
    return {
        "scope": "cold EvaluationHistory/ExperienceStore initialization only; no model, network or production workspace",
        "limits": "21 samples per arm; descriptive tails, coarse CPU accounting; no whole-product, HTTP deadline or Token/cost improvement claim",
        "owners": results,
    }


if __name__ == "__main__":
    raise SystemExit(main())

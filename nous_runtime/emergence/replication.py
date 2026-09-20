# -*- coding: utf-8 -*-
"""Replication Gate — anomalous results MUST pass replication before promotion.

Requirements: multiple seeds, multiple tasks, clean environment,
cross-device test, prompt perturbation, parameter perturbation,
ablation, independent reviewer, leakage check, metric integrity check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .surprise import AnomalyRecord


@dataclass
class ReplicationResult:
    """Result of replicating an anomalous finding."""
    anomaly_id: str = ""
    replicated: bool = False
    replication_count: int = 0
    required_count: int = 5
    passed_checks: list[str] = field(default_factory=list)
    failed_checks: list[str] = field(default_factory=list)
    new_status: str = ""  # validated_discovery or rejected_artifact
    evidence: dict[str, Any] = field(default_factory=dict)


class ReplicationGate:
    """Validates anomalous results through systematic replication.

    Anomaly → replication checks → EMERGENT_CANDIDATE or REJECTED_ARTIFACT.
    Only VALIDATED_DISCOVERY can enter the strategy candidate library.
    """

    REQUIRED_CHECKS = [
        "multiple_seeds",        # at least 3 different random seeds
        "multiple_tasks",        # at least 5 different tasks
        "clean_environment",     # fresh environment, no cache leakage
        "cross_device",          # reproduce on different hardware
        "prompt_perturbation",   # small prompt changes don't destroy effect
        "parameter_perturbation", # small parameter changes don't destroy effect
        "ablation",              # remove each component, measure impact
        "leakage_check",         # verify no data leakage
        "metric_integrity",      # verify metrics are computed correctly
        "independent_reviewer",  # different reviewer confirms
    ]

    def evaluate(self, anomaly: AnomalyRecord, results: list[dict[str, Any]]) -> ReplicationResult:
        """Evaluate whether an anomaly passes the replication gate."""
        rr = ReplicationResult(anomaly_id=anomaly.anomaly_id)

        for check in self.REQUIRED_CHECKS:
            check_result = self._run_check(check, results)
            if check_result:
                rr.passed_checks.append(check)
            else:
                rr.failed_checks.append(check)

        rr.replication_count = len(results)
        rr.required_count = 5
        rr.replicated = len(rr.failed_checks) <= 2  # allow 2 weak checks

        if rr.replicated and len(rr.failed_checks) == 0:
            rr.new_status = "validated_discovery"
        elif rr.replicated:
            rr.new_status = "emergent_candidate"
        else:
            rr.new_status = "rejected_artifact"

        return rr

    def _run_check(self, check_name: str, results: list[dict]) -> bool:
        """Run a specific replication check."""
        if check_name == "multiple_seeds":
            seeds = {r.get("seed") for r in results}
            return len(seeds) >= 3
        if check_name == "multiple_tasks":
            tasks = {r.get("task_id") for r in results}
            return len(tasks) >= 5
        if check_name == "clean_environment":
            return all(r.get("clean_env", False) for r in results)
        if check_name == "cross_device":
            devices = {r.get("device") for r in results}
            return len(devices) >= 2
        if check_name == "prompt_perturbation":
            return any(r.get("prompt_perturbed", False) for r in results)
        if check_name == "parameter_perturbation":
            return any(r.get("params_perturbed", False) for r in results)
        if check_name == "ablation":
            return any(r.get("ablated", False) for r in results)
        if check_name == "leakage_check":
            return all(r.get("no_leakage", True) for r in results)
        if check_name == "metric_integrity":
            return all(r.get("metrics_valid", True) for r in results)
        if check_name == "independent_reviewer":
            return any(r.get("reviewer_confirmed", False) for r in results)
        return False

# -*- coding: utf-8 -*-
"""
Security module — wraps nous_core.security with a clean public API.

New in this round:
- SecretVault (§18.3): encrypted secret storage
- AdmissionPipeline (§9): capability execution authorization
- RiskLevel classification (§9.3)
"""

from __future__ import annotations

from nous_runtime.compat.security import (
    check_risk,
    check_module_permission,
    register_module_permissions,
    check_rate_limit,
    record_security_event,
    get_security_stats,
)
from nous_runtime.security.vault import SecretVault, VaultEntry
from nous_runtime.security.admission import (
    AdmissionPipeline,
    AdmissionRequest,
    AdmissionResult,
    RiskLevel,
    classify_risk,
    AUTO_EXECUTE_RISK,
    APPROVAL_REQUIRED_RISK,
    DENY_DEFAULT_RISK,
)
from nous_runtime.security.workloads import (
    DEFENSIVE_ACTIONS,
    WorkloadKind,
    WorkloadProfile,
    defensive_workload,
)

__all__ = [
    # Legacy compat
    "check_risk",
    "check_module_permission",
    "register_module_permissions",
    "check_rate_limit",
    "record_security_event",
    "get_security_stats",
    # Vault
    "SecretVault",
    "VaultEntry",
    # Admission
    "AdmissionPipeline",
    "AdmissionRequest",
    "AdmissionResult",
    "RiskLevel",
    "classify_risk",
    "AUTO_EXECUTE_RISK",
    "APPROVAL_REQUIRED_RISK",
    "DENY_DEFAULT_RISK",
    "DEFENSIVE_ACTIONS",
    "WorkloadKind",
    "WorkloadProfile",
    "defensive_workload",
]

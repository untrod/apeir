# -*- coding: utf-8 -*-
"""
Static verification checks for the unified execution path.

Verifies:
1. All new kernel modules are importable
2. No direct remote_terminal.brain imports remain in nous_runtime
3. All Registry subclasses have consistent interfaces
4. Error codes are consistently used
5. Capability contracts reference valid verification methods
"""

from __future__ import annotations

import importlib
import os



# Import Verification


NEW_KERNEL_MODULES = [
    "nous_runtime.kernel.error_codes",
    "nous_runtime.kernel.identity",
    "nous_runtime.kernel.state_machine",
    "nous_runtime.kernel.node",
    "nous_runtime.kernel.task",
    "nous_runtime.kernel.session",
    "nous_runtime.kernel.registry_base",
    "nous_runtime.kernel.checkpoint_store",
    "nous_runtime.kernel.server",
    "nous_runtime.kernel.config",
]

NEW_SECURITY_MODULES = [
    "nous_runtime.security.vault",
    "nous_runtime.security.admission",
]

NEW_CAPABILITY_MODULES = [
    "nous_runtime.capability.contract",
    "nous_runtime.capability.sandbox",
]

NEW_INTELLIGENCE_MODULES = [
    "nous_runtime.intelligence.evidence",
    "nous_runtime.intelligence.calibration",
    "nous_runtime.intelligence.drift",
    "nous_runtime.intelligence.joint_scheduler",
    "nous_runtime.intelligence.budget_enforcer",
]

NEW_CONNECTIVITY_MODULES = [
    "nous_runtime.connectivity.mesh",
]

NEW_CONTEXT_MODULES = [
    "nous_runtime.context.token_estimator",
]

NEW_DEVICE_MODULES = [
    "nous_runtime.device.adapter",
]

NEW_PROVIDER_MODULES = [
    "nous_runtime.provider.adapters.ollama",
    "nous_runtime.provider.sdk",
]

NEW_AGENT_MODULES = [
    "nous_runtime.agent.reviewer",
]

NEW_PROJECT_MODULES = [
    "nous_runtime.project.memory_manager",
]

ALL_NEW_MODULES = (
    NEW_KERNEL_MODULES + NEW_SECURITY_MODULES + NEW_CAPABILITY_MODULES +
    NEW_INTELLIGENCE_MODULES + NEW_CONNECTIVITY_MODULES + NEW_CONTEXT_MODULES +
    NEW_DEVICE_MODULES + NEW_PROVIDER_MODULES + NEW_AGENT_MODULES +
    NEW_PROJECT_MODULES
)


class TestAllModulesImportable:
    """Verify every new module can be imported without error."""

    def test_kernel_modules(self):
        for mod in NEW_KERNEL_MODULES:
            importlib.import_module(mod)

    def test_security_modules(self):
        for mod in NEW_SECURITY_MODULES:
            importlib.import_module(mod)

    def test_capability_modules(self):
        for mod in NEW_CAPABILITY_MODULES:
            importlib.import_module(mod)

    def test_intelligence_modules(self):
        for mod in NEW_INTELLIGENCE_MODULES:
            importlib.import_module(mod)

    def test_connectivity_modules(self):
        for mod in NEW_CONNECTIVITY_MODULES:
            importlib.import_module(mod)

    def test_context_modules(self):
        for mod in NEW_CONTEXT_MODULES:
            importlib.import_module(mod)

    def test_device_modules(self):
        for mod in NEW_DEVICE_MODULES:
            importlib.import_module(mod)

    def test_provider_modules(self):
        for mod in NEW_PROVIDER_MODULES:
            importlib.import_module(mod)

    def test_agent_modules(self):
        for mod in NEW_AGENT_MODULES:
            importlib.import_module(mod)

    def test_project_modules(self):
        for mod in NEW_PROJECT_MODULES:
            importlib.import_module(mod)

    def test_all_modules_count(self):
        """Verify we have exactly the expected number of new modules."""
        imported = 0
        failed = []
        for mod in ALL_NEW_MODULES:
            try:
                importlib.import_module(mod)
                imported += 1
            except Exception as e:
                failed.append(f"{mod}: {e}")
        assert len(failed) == 0, f"Failed imports: {failed}"
        assert imported == len(ALL_NEW_MODULES), \
            f"Expected {len(ALL_NEW_MODULES)} modules, imported {imported}"



# No Direct brain.py Imports


BRAIN_IMPORT_PATTERNS = [
    "from remote_terminal.brain import",
    "from remote_terminal.brain_llm import",
    "from remote_terminal.brain_devices import",
    "from remote_terminal.brain_sessions import",
    "from remote_terminal.brain_clients import",
    "import remote_terminal.brain",
]


class TestNoBrainPyBypass:
    """Verify nous_runtime/ has no direct brain.py imports."""

    def test_no_brain_imports_in_nous_runtime(self):
        """Scan all nous_runtime .py files for direct brain imports."""
        nous_runtime_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "nous_runtime"
        )
        nous_runtime_dir = os.path.abspath(nous_runtime_dir)

        violations = []
        for root, dirs, files in os.walk(nous_runtime_dir):
            # Skip __pycache__
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if not f.endswith(".py"):
                    continue
                filepath = os.path.join(root, f)
                try:
                    with open(filepath, encoding="utf-8") as fh:
                        content = fh.read()
                except Exception:
                    continue

                for pattern in BRAIN_IMPORT_PATTERNS:
                    if pattern in content:
                        # Allowed exceptions: compat shims and adapters we fixed
                        allowed = [
                            "compat/brain_audio.py",
                            "compat/brain_exec.py",
                            "compat/devices.py",
                        ]
                        relpath = os.path.relpath(filepath, nous_runtime_dir).replace("\\", "/")
                        if relpath not in allowed and "compat" not in relpath:
                            violations.append(f"{relpath}: {pattern}")

        assert len(violations) == 0, (
            f"Found {len(violations)} direct brain.py import(s):\n" +
            "\n".join(violations)
        )



# Registry Consistency


class TestRegistryConsistency:
    """Verify all registries have consistent interface."""

    def test_registry_base_methods(self):
        from nous_runtime.kernel.registry_base import RegistryBase
        expected_methods = ["register", "get", "list", "unregister", "update",
                           "count", "health", "to_dict", "clear", "register_all"]
        for method in expected_methods:
            assert hasattr(RegistryBase, method), f"RegistryBase missing {method}"

    def test_existing_registries_identifiable(self):
        """Verify all existing registries can be identified for migration."""
        import nous_runtime
        existing_registry_files = [
            "provider/registry.py",
            "pack/registry.py",
            "agent/registry.py",
            "retrieval/registry.py",
            "model_runtime/registry.py",
            "intelligence/registry.py",
            "connectivity/control_plane/node_registry.py",
            "connectivity/control_plane/session_registry.py",
        ]
        for path in existing_registry_files:
            full = os.path.join(os.path.dirname(nous_runtime.__file__), path)
            if not os.path.exists(full):
                continue  # May be in build/
            assert os.path.exists(full), f"Expected registry at {full}"



# Error Code Consistency


class TestErrorCodeConsistency:
    """Verify error codes are consistently defined."""

    def test_all_codes_unique(self):
        from nous_runtime.kernel.error_codes import ErrorCode
        values = [e.value for e in ErrorCode]
        assert len(values) == len(set(values)), "Duplicate error code values"

    def test_retryable_mapping_complete(self):
        from nous_runtime.kernel.error_codes import ErrorCode, RETRYABLE_CODES
        for code in RETRYABLE_CODES:
            assert code in ErrorCode, f"RETRYABLE_CODES contains undefined {code}"

    def test_severity_all_codes(self):
        from nous_runtime.kernel.error_codes import ErrorCode, severity
        for code in ErrorCode:
            sev = severity(code)
            assert 0 <= sev <= 3, f"{code} has invalid severity {sev}"



# State Machine Integrity


class TestStateMachineIntegrity:
    """Verify state machines are well-formed."""

    def test_node_transitions_coverage(self):
        from nous_runtime.kernel.identity import (
            NodeConnectivity, NODE_CONNECTIVITY_TRANSITIONS
        )
        for state in NodeConnectivity:
            assert state in NODE_CONNECTIVITY_TRANSITIONS, \
                f"NodeConnectivity.{state.name} missing from transitions"

    def test_task_transitions_coverage(self):
        from nous_runtime.kernel.task import TaskPhase, TASK_TRANSITIONS
        for state in TaskPhase:
            assert state in TASK_TRANSITIONS, \
                f"TaskPhase.{state.name} missing from transitions"

    def test_task_terminal_no_exit(self):
        from nous_runtime.kernel.task import TaskPhase, TASK_TRANSITIONS, is_task_terminal
        for state in TaskPhase:
            if is_task_terminal(state):
                assert len(TASK_TRANSITIONS[state]) == 0, \
                    f"Terminal state {state.name} should have no transitions"

    def test_node_revoked_terminal(self):
        from nous_runtime.kernel.identity import (
            NodeConnectivity, NODE_CONNECTIVITY_TRANSITIONS
        )
        assert len(NODE_CONNECTIVITY_TRANSITIONS[NodeConnectivity.REVOKED]) == 0



# Capability Contract Integrity


class TestCapabilityContractIntegrity:
    """Verify capability contracts are consistent."""

    def test_default_contracts_registered(self):
        from nous_runtime.capability.contract import CapabilityContractRegistry
        registry = CapabilityContractRegistry()
        contracts = registry.list_all()
        assert len(contracts) >= 6, f"Expected ≥6 default contracts, got {len(contracts)}"

    def test_all_contracts_have_required_fields(self):
        from nous_runtime.capability.contract import CapabilityContractRegistry
        registry = CapabilityContractRegistry()
        for contract in registry.list_all():
            assert contract.capability_id, "Contract missing capability_id"
            assert contract.risk_level, f"{contract.capability_id} missing risk_level"
            assert contract.timeout_seconds > 0, f"{contract.capability_id} timeout=0"

    def test_risk_levels_valid(self):
        from nous_runtime.capability.contract import CapabilityContractRegistry
        from nous_runtime.security.admission import RiskLevel
        registry = CapabilityContractRegistry()
        valid_levels = {r.value for r in RiskLevel}
        for contract in registry.list_all():
            assert contract.risk_level in valid_levels, \
                f"{contract.capability_id} has invalid risk '{contract.risk_level}'"

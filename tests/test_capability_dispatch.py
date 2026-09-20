# -*- coding: utf-8 -*-
"""Executor-type dispatch tests — v0.2.0 pipeline completion.

Covers the subprocess executor, the structured NOUS_EXECUTOR_UNSUPPORTED
path for connector/node/unknown executor types, the provider-path
regression, and the device.flash acceptance scenario (privileged +
destructive capability must require approval).
"""
from __future__ import annotations

import sys

import pytest

from nous_runtime.capability.resolver import execute_capability_observation
from nous_runtime.kernel.windows_sandbox import executable_path


requires_strong_sandbox = pytest.mark.skipif(
    executable_path() is None,
    reason="Windows Sandbox requires the post-feature-enable reboot",
)


def _register(name: str, **kwargs):
    from remote_terminal.nous_core.capability import register_capability

    return register_capability(name, **kwargs)


def _unregister(name: str):
    from remote_terminal.nous_core.capability import unregister_capability

    unregister_capability(name)


# Subprocess executor

@requires_strong_sandbox
def test_subprocess_capability_executes():
    """A registered subprocess capability runs its declared command."""
    from remote_terminal.nous_core.capability import CAT_SOFTWARE, EXECUTOR_SUBPROCESS

    _register(
        "test.disp.echo",
        category=CAT_SOFTWARE,
        provider="test-disp",
        risk="low",
        executor_type=EXECUTOR_SUBPROCESS,
        metadata={"command": [sys.executable, "-c", "print('hi')"]},
    )
    try:
        obs = execute_capability_observation("test.disp.echo")
    finally:
        _unregister("test.disp.echo")

    assert obs.status == "success", obs.errors
    assert "hi" in obs.data["result"]["stdout"]
    assert obs.data["result"]["exit_code"] == 0
    assert obs.metadata["executor_type"] == "subprocess"


@requires_strong_sandbox
def test_subprocess_param_placeholder():
    """{name} argv elements are replaced with str(params[name])."""
    from remote_terminal.nous_core.capability import CAT_SOFTWARE, EXECUTOR_SUBPROCESS

    _register(
        "test.disp.param",
        category=CAT_SOFTWARE,
        provider="test-disp",
        risk="low",
        executor_type=EXECUTOR_SUBPROCESS,
        metadata={"command": [sys.executable, "-c", "{code}"]},
    )
    try:
        obs = execute_capability_observation("test.disp.param", code="print(21*2)")
    finally:
        _unregister("test.disp.param")

    assert obs.status == "success", obs.errors
    assert "42" in obs.data["result"]["stdout"]


@requires_strong_sandbox
def test_subprocess_nonzero_exit_maps_to_failure():
    """Non-zero exit codes become NOUS_SUBPROCESS_FAILED."""
    from remote_terminal.nous_core.capability import CAT_SOFTWARE, EXECUTOR_SUBPROCESS

    _register(
        "test.disp.fails",
        category=CAT_SOFTWARE,
        provider="test-disp",
        risk="low",
        executor_type=EXECUTOR_SUBPROCESS,
        metadata={"command": [sys.executable, "-c", "import sys; sys.exit(3)"]},
    )
    try:
        obs = execute_capability_observation("test.disp.fails")
    finally:
        _unregister("test.disp.fails")

    assert obs.status == "failed"
    assert obs.metadata["error_code"] == "NOUS_SUBPROCESS_FAILED"
    assert obs.metadata["exit_code"] == 3


def test_subprocess_missing_binary_maps_to_failure():
    """An unlaunchable command becomes NOUS_SUBPROCESS_FAILED, not a crash."""
    from remote_terminal.nous_core.capability import CAT_SOFTWARE, EXECUTOR_SUBPROCESS

    _register(
        "test.disp.nobinary",
        category=CAT_SOFTWARE,
        provider="test-disp",
        risk="low",
        executor_type=EXECUTOR_SUBPROCESS,
        metadata={"command": ["definitely_not_a_real_binary_xyz"]},
    )
    try:
        obs = execute_capability_observation("test.disp.nobinary")
    finally:
        _unregister("test.disp.nobinary")

    assert obs.status == "failed"
    assert obs.metadata["error_code"] == "NOUS_SUBPROCESS_FAILED"


def test_subprocess_missing_command_is_misconfigured():
    """subprocess executor without a declared command is misconfigured."""
    from remote_terminal.nous_core.capability import CAT_SOFTWARE, EXECUTOR_SUBPROCESS

    _register(
        "test.disp.nocmd",
        category=CAT_SOFTWARE,
        provider="test-disp",
        risk="low",
        executor_type=EXECUTOR_SUBPROCESS,
    )
    try:
        obs = execute_capability_observation("test.disp.nocmd")
    finally:
        _unregister("test.disp.nocmd")

    assert obs.status == "failed"
    assert obs.metadata["error_code"] == "NOUS_SUBPROCESS_MISCONFIGURED"


def test_subprocess_missing_placeholder_param_is_misconfigured():
    """A {placeholder} without a matching caller param fails safely."""
    from remote_terminal.nous_core.capability import CAT_SOFTWARE, EXECUTOR_SUBPROCESS

    _register(
        "test.disp.noparam",
        category=CAT_SOFTWARE,
        provider="test-disp",
        risk="low",
        executor_type=EXECUTOR_SUBPROCESS,
        metadata={"command": [sys.executable, "{script}"]},
    )
    try:
        obs = execute_capability_observation("test.disp.noparam")
    finally:
        _unregister("test.disp.noparam")

    assert obs.status == "failed"
    assert obs.metadata["error_code"] == "NOUS_SUBPROCESS_MISCONFIGURED"
    assert "script" in "; ".join(obs.errors)


# Unsupported executor types

def test_connector_node_and_unknown_executor_unsupported():
    """connector/node/unknown executor types return a structured error."""
    from remote_terminal.nous_core.capability import CAT_DEVICE

    for executor_type in ("connector", "node", "stm32_programmer"):
        name = f"test.disp.unsup_{executor_type[:8]}"
        _register(
            name,
            category=CAT_DEVICE,
            provider="test-disp",
            risk="low",
            executor_type=executor_type,
        )
        try:
            obs = execute_capability_observation(name)
        finally:
            _unregister(name)

        assert obs.status == "failed"
        assert obs.metadata["error_code"] == "NOUS_EXECUTOR_UNSUPPORTED"
        assert obs.metadata["executor_type"] == executor_type
        assert executor_type in "; ".join(obs.errors)


# Provider path regression

def test_provider_path_regression():
    """Provider-executor capabilities keep the resolve→gate→invoke path."""
    from remote_terminal.nous_core.provider import (
        Provider,
        register_adapter,
        unregister_adapter,
    )

    class EchoProvider(Provider):
        provider_id = "dispatch_regression_test"
        provider_name = "Dispatch Regression Test"

        def list_capabilities(self):
            return ["test.disp.provider_echo"]

        def invoke(self, capability_id, **params):
            return {"ok": True, "value": params["value"]}

        def health(self):
            return {"status": "ok"}

    provider = EchoProvider()
    register_adapter(provider)
    try:
        obs = execute_capability_observation("test.disp.provider_echo", value=7)
    finally:
        unregister_adapter(provider.provider_id)
        _unregister("test.disp.provider_echo")

    assert obs.status == "success", obs.errors
    assert obs.data["result"] == {"ok": True, "value": 7}
    assert obs.metadata["provider_id"] == provider.provider_id


# Acceptance: device.flash requires approval

def test_device_flash_requires_approval(tmp_path):
    """The motivating scenario: privileged destructive flashing needs approval.

    device.flash declares category=device, executor_type=stm32_programmer,
    side_effect=destructive, privileged=True, reversibility=partial — the
    gate must answer ASK_APPROVAL, and the risk envelope must reflect the
    declared privileged flag.
    """
    from remote_terminal.nous_core.capability import (
        CAT_DEVICE,
        REVERSIBILITY_PARTIALLY,
        SIDE_EFFECT_DESTRUCTIVE,
    )
    from nous_runtime.capability.resolver import (
        _infer_reversibility,
        _infer_side_effect,
    )
    from nous_runtime.governance.contracts import ActionProposal, AuthorizationContext
    from nous_runtime.governance.gate import ExecutionAuthorizationGate
    from nous_runtime.governance.risk_engine import assess_risk
    from nous_runtime.governance.store import GovernanceStore

    _register(
        "device.flash",
        category=CAT_DEVICE,
        provider="stm32",
        risk="high",
        executor_type="stm32_programmer",
        side_effect_class=SIDE_EFFECT_DESTRUCTIVE,
        reversibility=REVERSIBILITY_PARTIALLY,
        model_uncertainty=0.0,
        idempotent=False,
        privileged=True,
        locality="local",
        connection_type="usb",
    )
    try:
        gate = ExecutionAuthorizationGate(store=GovernanceStore(tmp_path))
        proposal = ActionProposal(
            action_type="capability.execute",
            capability_id="device.flash",
            side_effect_class=_infer_side_effect("device.flash"),
            reversibility=_infer_reversibility("device.flash"),
        )
        context = AuthorizationContext(
            subject_type="user",
            subject_id="owner",
            authn_method="test",
            authn_confidence=1.0,
        )

        # Declared metadata drives the proposal semantics
        assert proposal.side_effect_class == "destructive"
        assert proposal.reversibility == "partially_reversible"

        decision = gate.evaluate(proposal, context)
        assert decision.action_mode == "ASK_APPROVAL"

        envelope = assess_risk(
            proposal, context, gate._lookup_capability("device.flash")
        )
        assert envelope.privilege_risk >= 0.7

        # End-to-end: execution must not silently succeed
        obs = execute_capability_observation("device.flash")
        assert obs.status == "failed"
        assert obs.metadata["error_code"] in {
            "NOUS_EXECUTOR_UNSUPPORTED",
            "NOUS_APPROVAL_REQUIRED",
        }
    finally:
        _unregister("device.flash")

from __future__ import annotations

import pytest

from nous_runtime.governance.effect_gate import EffectGate


def test_failed_effect_is_not_committed_and_can_be_retried() -> None:
    gate = EffectGate()
    action, _ = gate.propose_action("file_write", "report.md", {"size": 10})
    approval = gate.request_approval(action, approver="test")

    def fail(_params):
        raise OSError("disk unavailable")

    failed = gate.execute(action, approval, fail)

    assert failed.success is False
    assert gate.was_executed(action.action_hash) is False
    retried = gate.execute(
        action,
        gate.request_approval(action, approver="test-retry"),
        lambda _params: {"written": True},
    )
    assert retried.success is True
    assert gate.was_executed(action.action_hash) is True


def test_successful_effect_is_replay_protected() -> None:
    gate = EffectGate()
    action, _ = gate.propose_action("file_write", "report.md", {"size": 10})
    receipt = gate.execute(
        action,
        gate.request_approval(action, approver="test"),
        lambda _params: {"written": True},
    )

    assert receipt.success is True
    with pytest.raises(ValueError, match="replay denied"):
        gate.execute(
            action,
            gate.request_approval(action, approver="test-replay"),
            lambda _params: {"written": True},
        )

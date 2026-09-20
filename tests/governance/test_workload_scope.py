from __future__ import annotations

import pytest

from nous_runtime.core.errors import CapabilityError
from nous_runtime.security.workloads import (
    WorkloadKind,
    WorkloadProfile,
    defensive_workload,
)
from nous_runtime.intelligence.joint_scheduler import (
    JointScheduler,
    SchedulingConstraints,
)
from nous_runtime.kernel.task import TaskFingerprint


def test_defensive_workload_requires_authorized_assets():
    with pytest.raises(CapabilityError, match="authorized assets"):
        defensive_workload("log_analysis", authorized_assets=[])


def test_defensive_workload_records_scope_and_parallelism():
    profile = defensive_workload(
        "configuration_audit",
        authorized_assets=["asset-1"],
        target_nodes=["edge-1"],
        max_parallel_lanes=4,
    )

    assert profile.to_dict() == {
        "kind": "defensive_security",
        "action": "configuration_audit",
        "required_capabilities": [
            "security.defensive.configuration_audit"
        ],
        "target_nodes": ["edge-1"],
        "authorized_assets": ["asset-1"],
        "max_parallel_lanes": 4,
        "metadata": {},
    }


def test_offensive_or_unbounded_workload_is_rejected():
    with pytest.raises(CapabilityError, match="defensive security boundary"):
        WorkloadProfile(
            kind=WorkloadKind.COMPUTE,
            action="credential_dump",
        ).validate()
    with pytest.raises(CapabilityError, match="parallel lane"):
        WorkloadProfile(max_parallel_lanes=65).validate()


def test_joint_scheduler_builds_bounded_lanes_across_models_and_nodes():
    result = JointScheduler().schedule_lanes(
        TaskFingerprint(task_type="analysis"),
        [
            {
                "node_id": "edge-1",
                "name": "Edge 1",
                "online": True,
                "capabilities": ["compute"],
                "trust_zone": "managed",
            },
            {
                "node_id": "edge-2",
                "name": "Edge 2",
                "online": True,
                "capabilities": ["compute"],
                "trust_zone": "managed",
            },
        ],
        [
            {"instance_key": "model-a", "capabilities": ["reasoning"]},
            {"instance_key": "model-b", "capabilities": ["reasoning"]},
        ],
        SchedulingConstraints(
            required_capabilities=["reasoning"],
            required_node_capabilities=["compute"],
            allowed_trust_zones=["managed"],
            max_parallel_lanes=3,
        ),
    )

    assert result.ok
    assert result.value.scheduled_lanes == 3
    assert len({
        (path.node_id, path.model_instance_key)
        for path in result.value.paths
    }) == 3


def test_joint_scheduler_rejects_unscoped_defensive_execution():
    result = JointScheduler().schedule(
        TaskFingerprint(task_type="security"),
        [{"node_id": "edge-1", "online": True}],
        [{
            "instance_key": "model-a",
            "capabilities": ["security.defensive.log_analysis"],
        }],
        SchedulingConstraints(
            required_capabilities=["security.defensive.log_analysis"],
        ),
    )

    assert not result.ok
    assert result.code.value == "PERMISSION_DENIED"

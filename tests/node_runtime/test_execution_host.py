from __future__ import annotations

import hashlib
import json

from nous_runtime.node_runtime.execution_host import evaluate_execution_preflight


def _inventory(*, architecture="arm64", cargo=True, python_version="3.12.10"):
    return {
        "host": {"architecture": architecture},
        "tools": {
            "python": {"available": True, "version": python_version},
            "cargo": {"available": cargo, "version": "1.97.1" if cargo else ""},
        },
    }


def test_preflight_accepts_matching_architecture_and_tools():
    result = evaluate_execution_preflight(
        _inventory(),
        {"architecture": "aarch64", "tools": ["python >= 3.12", "cargo"]},
    )

    assert result["status"] == "ELIGIBLE"
    assert result["eligible"] is True
    assert result["reasons"] == []
    assert result["authority"] == "none"
    assert result["grants_capabilities"] is False


def test_preflight_reports_each_missing_or_incompatible_fact():
    result = evaluate_execution_preflight(
        _inventory(architecture="amd64", cargo=False, python_version="3.11.9"),
        {"architecture": "arm64", "tools": ["python >= 3.12", "cargo"]},
    )

    assert result["status"] == "INELIGIBLE"
    assert result["eligible"] is False
    assert result["reasons"] == [
        "architecture mismatch: requires arm64, host is amd64",
        "tool python 3.11.9 does not satisfy >= 3.12",
        "tool cargo missing",
    ]


def test_execution_host_inventory_is_in_node_status(tmp_path):
    from nous_runtime.node_runtime.service import NodeRuntimeConfig, NodeRuntimeService

    service = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
    status = service.run_once()

    inventory = status["execution_host"]
    assert inventory["schema"] == "apeir.execution-host-inventory/v1"
    assert inventory["host"]["architecture"]
    assert inventory["tools"]["python"]["available"] is True
    assert inventory["authority"] == "none"
    assert inventory["grants_capabilities"] is False


def test_preflight_is_a_bounded_node_workload(tmp_path):
    from nous_runtime.node_runtime.service import NodeRuntimeConfig, NodeRuntimeService

    service = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
    result = service.execute_workload(
        "preflight-1",
        "node.execution-preflight",
        {"architecture": "arm64", "tools": ["python >= 3.12"]},
    )

    assert result["state"] == "COMPLETED"
    assert result["output"]["status"] in {"ELIGIBLE", "INELIGIBLE"}
    assert result["output"]["authority"] == "none"


def test_execution_host_inventory_becomes_content_addressed_evidence(tmp_path):
    from nous_runtime.node_runtime.service import NodeRuntimeConfig, NodeRuntimeService

    service = NodeRuntimeService(NodeRuntimeConfig(state_dir=tmp_path / "node"))
    result = service.execute_workload(
        "host-evidence-1", "node.execution-host-evidence", {"refresh": False}
    )

    assert result["state"] == "COMPLETED"
    evidence = result["output"]
    assert evidence["authority"] == "none"
    assert evidence["grants_capabilities"] is False
    assert evidence["evidence_ref"] == "sha256:" + evidence["digest"]
    content = service.artifact_store.resolve(evidence["evidence_ref"]).read_bytes()
    assert hashlib.sha256(content).hexdigest() == evidence["digest"]
    inventory = json.loads(content)
    assert inventory["schema"] == "apeir.execution-host-inventory/v1"
    assert inventory["authority"] == "none"

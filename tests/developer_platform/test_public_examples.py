"""Public examples use canonical owners and retain evidence of negative paths."""

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_example(path, name, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "sdk/provider/python"))
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_provider_example_uses_real_signed_work_and_explicit_policy(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    module = load_example(
        ROOT / "examples/hello_provider/run_example.py", "hello_sdk_host", monkeypatch
    )
    result = asyncio.run(module.run(tmp_path))
    work = result["work"]
    assert work["state"] == "COMMITTED"
    assert result["output"] == {"ok": True, "message": "Hello, Developer!"}
    assert result["unknown_capability_decision"] == "DENY"
    assert result["missing_permission_decision"] == "UNKNOWN"
    assert result["mutation_decision"] == "REQUIRE_APPROVAL"
    assert result["removed_provider_denied"] is True
    assert result["provider_error"]["ok"] is False
    assert result["conformance"]["summary"]["total_passed"] == 2
    assert result["conformance"]["summary"]["total_failed"] == 0
    receipt = work["result_summary"]["remote_execution_receipt"]
    assert receipt["operation_id"] == work["work_id"]
    assert receipt["node_id"] == work["assigned_node"]
    assert receipt["signed_envelope"]["signature"]
    assert any(
        row["event_type"] == "execution.admitted"
        and json.loads(row["evidence_json"])["work_id"] == work["work_id"]
        for row in result["audit"]
    )
    from nous_provider.runtime import ContentAddressedArtifactStore, ProviderRegistry

    cas = ContentAddressedArtifactStore(tmp_path / ".nous/relay/artifacts")
    assert all(
        cas.verify("sha256:" + ref.removeprefix("artifact://sha256/"))
        for ref in (
            *work["input_artifacts"],
            *work["output_artifacts"],
            *work["evidence_refs"],
        )
    )
    assert ProviderRegistry().get("example.hello") is None


def test_provider_failure_maps_to_failed_work_without_commit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module = load_example(
        ROOT / "examples/hello_provider/run_example.py",
        "hello_sdk_failure",
        monkeypatch,
    )
    monkeypatch.setattr(
        module.HelloProvider,
        "invoke",
        lambda *a, **kw: {"ok": False, "error": "deterministic fake Provider failure"},
    )
    from nous_provider.runtime import DistributedWorkStore, DistributedWorkError

    with pytest.raises(DistributedWorkError, match="FAILED"):
        asyncio.run(module.run(tmp_path))
    assert (
        DistributedWorkStore(tmp_path / ".nous/relay")
        .get("hello-read-work")
        .state.value
        == "FAILED"
    )


@pytest.mark.parametrize(
    "work_id,node_id,args",
    [
        ("wrong-work", "node", {}),
        ("work", "wrong-node", {}),
        ("work", "node", {"authorization_id": "forged"}),
        ("work", "node", None),
    ],
)
def test_host_rejects_wrong_binding_before_provider_call(
    tmp_path, monkeypatch, work_id, node_id, args
):
    module = load_example(
        ROOT / "examples/hello_provider/run_example.py",
        "hello_sdk_binding",
        monkeypatch,
    )
    from nous_provider.runtime import GovernanceRequest

    request = GovernanceRequest(
        operation_id="work",
        work_id="work",
        capability_id="example.greet",
        resource_id="example.hello",
        subject_id="host",
        node_id="node",
    )
    host = module._AuthorizedHello(None, None, None, request)
    if args is None:
        args = {"authorization_id": request.authorization_id}
    with pytest.raises(PermissionError, match="binding mismatch"):
        host.execute_bound(args, workload_id=work_id, node_id=node_id, binding={})


def test_skill_install_load_and_persistent_disable_without_execution(
    tmp_path, monkeypatch
):
    module = load_example(
        ROOT / "examples/hello_skill/run_example.py", "hello_skill_example", monkeypatch
    )
    result = module.run(tmp_path, ROOT / "examples/hello_skill/verified-device-review")
    assert result["loaded"]["ok"]
    assert result["record"]["authority"] == "none"
    assert result["record"]["risk"] == "high"
    assert "device.firmware.update" in result["record"]["requested_capabilities"]
    assert result["artifact_integrity"]
    assert result["record"]["digest"] and result["record"]["artifact_ref"]
    assert result["agent_install_denied"]["ok"] is False
    assert result["operation_not_executable_as_skill"]["ok"] is False
    assert result["disabled_after_reopen"]["ok"] is False
    assert result["execution_performed"] is False


def test_examples_do_not_require_internal_runtime_imports():
    for path in (
        ROOT / "examples/hello_provider/hello_provider.py",
        ROOT / "examples/hello_provider/run_example.py",
        ROOT / "examples/hello_skill/run_example.py",
    ):
        assert "from nous_runtime" not in path.read_text()
        assert "import nous_runtime" not in path.read_text()


def test_public_workflow_definition_runs_and_retains_history(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from nous_runtime.workflow import WorkflowRuntime
    from nous_runtime.workflow.cli import workflow_app

    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    path = str(ROOT / "examples/hello_workflow/workflow.json")
    for command in ("validate", "register"):
        result = runner.invoke(workflow_app, [command, path, "--json"])
        assert result.exit_code == 0, result.output
    result = runner.invoke(workflow_app, ["run", "example.workflow", "--json"])
    assert result.exit_code == 0, result.output
    run = json.loads(result.output)
    assert run["state"] == "completed"
    assert run["outputs"]["hello"]["value"] == "Hello from APEIR"
    assert (
        WorkflowRuntime(str(tmp_path)).store.history("example.workflow")[0].run_id
        == run["run_id"]
    )

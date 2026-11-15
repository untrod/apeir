"""Work integration contracts; the Kernel and remote service are explicit fixtures."""

import asyncio
import json

import pytest
from typer.testing import CliRunner

from nous_runtime.extensions.admission import ExtensionAdmissionService
from nous_runtime.extensions.cli import extension_app
from nous_runtime.extensions.executor import UnifiedExtensionExecutor
from nous_runtime.extensions.permissions import ExtensionPermissionService
from nous_runtime.extensions.registry import ExtensionRegistry
from nous_runtime.extensions.work_tools import (
    WorkExtensionTools,
    work_extension_records,
)
from nous_runtime.governance.broker import ApprovalBroker
from nous_runtime.governance.contracts import AuthorizationContext
from nous_runtime.governance.store import GovernanceStore
from nous_runtime.tools import ToolCatalog
from nous_runtime.work import DecisionStatus, WorkDecision, WorkHarness
from nous_runtime.work.loop import AgentLoop
from nous_runtime.events import RunState
from tests.extensions.test_extension_executor import (
    FakeAdapter,
    FakeKernel,
    make_openapi,
)


@pytest.fixture
def package(tmp_path, request):
    source = tmp_path / "openapi.json"
    make_openapi(source)
    if hasattr(request, "param"):
        value = json.loads(source.read_text())
        value["paths"]["/items/{id}"]["get"]["parameters"][0]["schema"] = request.param
        source.write_text(json.dumps(value))
    root = tmp_path / "workspace"
    registry = ExtensionRegistry(root / ".nous" / "extensions")
    extension_id = registry.install(source).extension_id
    kernel, adapter = FakeKernel(), FakeAdapter()
    admission = ExtensionAdmissionService(registry, kernel)
    asyncio.run(admission.admit(extension_id))
    permissions = ExtensionPermissionService(
        registry,
        admission,
        ApprovalBroker(GovernanceStore(root / ".nous" / "governance")),
    )
    context = AuthorizationContext(
        subject_type="user",
        subject_id="local-user",
        authn_method="cli_os_user",
        authn_confidence=1.0,
    )
    _, request = permissions.request(extension_id, context)
    asyncio.run(permissions.approve(extension_id, request.request_id, "admin"))
    executor = UnifiedExtensionExecutor(registry, kernel, {"openapi": adapter})
    return root, registry, extension_id, kernel, adapter, executor


def enable(registry, extension_id, value=True):
    record = registry.get_record(extension_id)
    return registry.set_work_enabled(
        extension_id,
        value,
        expected_digest=record["digest"],
        expected_version=record["version"],
    )


def setup(package):
    root, registry, extension_id, _, _, executor = package
    harness = WorkHarness(root)
    snapshot = harness.create("Inspect the reviewed extension result")
    bridge = WorkExtensionTools(root, snapshot, executor=executor)
    enable(registry, extension_id)
    catalog = ToolCatalog()
    bridge.register(catalog)
    tool = catalog.discover()[0]["tool_id"]
    arguments = {"id": "42"}
    snapshot.pending_action = {
        "tool": tool,
        "action_sequence": 1,
        "arguments_digest": AgentLoop._arguments_digest(arguments),
    }
    snapshot.state = RunState.EXECUTING
    harness.persist_progress(
        snapshot, "work.action.dispatched", {"action": snapshot.pending_action}
    )
    return harness, snapshot, bridge, catalog, tool, arguments


def test_only_opted_in_tools_load_and_read_only_never_exposes_them(package):
    root, registry, extension_id, kernel, adapter, executor = package
    snapshot = WorkHarness(root).create("Inspect extensions")
    catalog = ToolCatalog()
    WorkExtensionTools(root, snapshot, executor=executor).register(catalog)
    assert catalog.discover() == ()
    enable(registry, extension_id)
    snapshot.execution_options["read_only"] = True
    WorkExtensionTools(root, snapshot, executor=executor).register(catalog)
    assert catalog.discover() == ()
    assert not kernel.execution_calls and not adapter.calls
    assert (
        work_extension_records(root)["records"][0]["status"] == "KERNEL_CHECK_REQUIRED"
    )


def test_original_work_key_receipt_and_no_repeated_effect(package):
    _, _, bridge, catalog, tool, arguments = setup(package)
    first = catalog.execute(tool, arguments)
    second = catalog.execute(tool, arguments)
    _, _, extension_id, kernel, adapter, _ = package
    assert first["ok"] is True and first["extension_id"] == extension_id
    assert first["receipt"]["permit_id"] == "extension-permit-fixture"
    assert bridge.snapshot.run_id in kernel.execution_calls[0][1]
    assert first["verification"] == "unverified_executor_report"
    assert second["ok"] is False and second["recovery_required"]
    assert len(adapter.calls) == 1


def test_receipt_permission_failure_after_dispatch_remains_unknown(
    package, monkeypatch
):
    _, _, _, catalog, tool, arguments = setup(package)

    def unavailable_receipt(*args, **kwargs):
        raise PermissionError("Receipt destination became read-only after dispatch")

    monkeypatch.setattr(package[1], "record_execution_receipt", unavailable_receipt)
    result = catalog.execute(tool, arguments)
    assert len(package[4].calls) == 1

    assert result["ok"] is False
    assert result.get("state") == "UNKNOWN"
    assert result.get("recovery_required") is True
    repeated = catalog.execute(tool, arguments)
    assert repeated.get("recovery_required") is True
    assert len(package[4].calls) == 1


def test_receipt_failure_pauses_original_work_and_restart_does_not_replay(
    package, monkeypatch
):
    harness, snapshot, _, catalog, tool, arguments = setup(package)
    snapshot.pending_action = {}
    harness.persist_progress(snapshot, "work.progress", {"action": {}})

    def unavailable_receipt(*args, **kwargs):
        raise PermissionError("Receipt write denied after adapter returned")

    monkeypatch.setattr(package[1], "record_execution_receipt", unavailable_receipt)
    decisions = iter(
        (
            WorkDecision(
                DecisionStatus.CONTINUE,
                "Load extension schemas",
                tool_name="catalog_expand",
                tool_arguments={"category": "extension"},
            ),
            WorkDecision(
                DecisionStatus.CONTINUE,
                "Invoke once",
                tool_name=tool,
                tool_arguments=arguments,
            ),
        )
    )
    original = harness.run(
        snapshot.run_id, deliberator=lambda _: next(decisions), tools=catalog
    )
    assert original.state is RunState.RECOVERY_REQUIRED
    assert original.pending_action["tool"] == tool
    assert len(package[4].calls) == 1
    restarted = WorkHarness(package[0])
    recovered = restarted.resume(
        snapshot.run_id,
        deliberator=lambda _: WorkDecision(
            DecisionStatus.BLOCKED, "Inspect original effect"
        ),
        tools=catalog,
    )
    assert (
        recovered.run_id == snapshot.run_id
        and recovered.state is not RunState.COMPLETED
    )
    assert len(package[4].calls) == 1


@pytest.mark.parametrize("change", ["disable", "remove", "revoke", "arguments", "work"])
def test_stale_tool_cannot_cross_lifecycle_or_original_action(package, change):
    harness, snapshot, _, catalog, tool, arguments = setup(package)
    root, registry, extension_id, kernel, adapter, _ = package
    if change == "disable":
        enable(ExtensionRegistry(registry.root), extension_id, False)
    elif change == "remove":
        registry.remove(extension_id)
    elif change == "revoke":
        registry.record_revocation(
            extension_id,
            {
                "receipt_id": "revoked",
                "extension_id": extension_id,
                "normalized_digest": registry.get_record(extension_id)["digest"],
            },
        )
    elif change == "arguments":
        arguments["id"] = "changed"
    else:
        snapshot.pending_action = {}
        harness.persist_progress(snapshot, "work.progress", {"action": {}})
    result = catalog.execute(tool, arguments)
    assert result["ok"] is False
    assert not kernel.execution_calls and not adapter.calls
    if change == "disable":
        assert work_extension_records(root)["records"][0]["enabled"] is False


@pytest.mark.parametrize("change", ["disable", "cancel"])
def test_disable_while_kernel_permit_is_pending_prevents_dispatch(package, change):
    harness, snapshot, _, catalog, tool, arguments = setup(package)
    _, registry, extension_id, kernel, adapter, _ = package
    original = kernel.authorize_extension_execution

    async def disable_then_grant(*args, **kwargs):
        if change == "disable":
            enable(ExtensionRegistry(registry.root), extension_id, False)
        else:
            harness.cancel(snapshot.run_id, reason="Operator cancelled before dispatch")
        return await original(*args, **kwargs)

    kernel.authorize_extension_execution = disable_then_grant
    result = catalog.execute(tool, arguments)
    assert result["ok"] is False
    assert not adapter.calls


def test_work_flag_is_digest_bound_and_cli_can_restore_disabled_state(package):
    root, registry, extension_id, _, _, _ = package
    enable(registry, extension_id)
    runner = CliRunner()
    result = runner.invoke(
        extension_app,
        [
            "work-enable",
            extension_id,
            "--registry",
            str(registry.root),
            "--disabled",
            "--json",
        ],
    )
    assert result.exit_code == 0 and json.loads(result.stdout)["work_enabled"] is False
    assert ExtensionRegistry(registry.root).verify(extension_id)
    record = registry.get_record(extension_id)
    with pytest.raises(PermissionError):
        registry.set_work_enabled(
            extension_id,
            True,
            expected_digest="sha256:" + "a" * 64,
            expected_version=record["version"],
        )
    index = json.loads(registry.index_path.read_text())
    index["extensions"][extension_id]["work_enabled"] = True
    registry.index_path.write_text(json.dumps(index))
    with pytest.raises(ValueError, match="Work state"):
        registry.verify(extension_id)
    assert work_extension_records(root)["diagnostics"][0]["state"] == "BLOCKED"


def test_original_work_records_extension_result_and_restores_it(package, monkeypatch):
    harness, snapshot, _, catalog, tool, arguments = setup(package)
    from nous_runtime.work.components import build_work_components

    async def connect(endpoint, principal_id):
        assert principal_id == "agent.apeir.work"
        return package[3]

    async def close():
        return None

    monkeypatch.setattr("compat.nki_client.NKIClient.connect", staticmethod(connect))
    monkeypatch.setattr(package[3], "close", close, raising=False)
    monkeypatch.setattr(
        "nous_runtime.extensions.openapi.OpenApiExecutionAdapter", lambda: package[4]
    )
    monkeypatch.setattr(
        "nous_runtime.cli.provider_setup.load_providers_from_config", lambda *_: 1
    )
    monkeypatch.setattr(
        "nous_runtime.model_runtime.get_gateway_facade", lambda **_: object()
    )
    catalog = build_work_components(package[0], harness.require(snapshot.run_id)).tools
    assert catalog.require(tool).metadata["extension_id"] == package[2]
    snapshot.pending_action = {}
    decisions = iter(
        (
            WorkDecision(
                DecisionStatus.CONTINUE,
                "Discover extension tools",
                tool_name="catalog_expand",
                tool_arguments={"category": "extension"},
            ),
            WorkDecision(
                DecisionStatus.CONTINUE,
                "Inspect reviewed item",
                tool_name=tool,
                tool_arguments=arguments,
            ),
            WorkDecision(DecisionStatus.COMPLETE, "Record inspected", output="done"),
        )
    )
    harness.persist_progress(snapshot, "work.progress", {"action": {}})
    completed = harness.run(
        snapshot.run_id, deliberator=lambda _: next(decisions), tools=catalog
    )
    records = WorkHarness(package[0]).require(snapshot.run_id).observations
    invocation = next(item for item in records if item["tool"] == tool)
    assert invocation["result"]["receipt"]["extension_id"] == package[2]
    assert invocation["result"]["result"] == {"value": "ok"}
    assert len(package[4].calls) == 1
    assert completed.run_id == snapshot.run_id


@pytest.mark.parametrize(
    "package", [{"$ref": "https://schema.example.invalid/private"}], indirect=True
)
def test_untrusted_schema_cannot_download_remote_references(package, monkeypatch):
    def unexpected_network(*args, **kwargs):
        raise AssertionError("Schema validation attempted a network request")

    monkeypatch.setattr("urllib.request.urlopen", unexpected_network)
    _, _, _, catalog, tool, arguments = setup(package)
    result = catalog.execute(tool, arguments)
    assert result["ok"] is False
    assert not package[3].execution_calls and not package[4].calls


def test_damaged_enabled_package_blocks_its_tools_without_breaking_host_tools(package):
    root, registry, extension_id, kernel, adapter, executor = package
    enable(registry, extension_id)
    package_root = registry.package_path(extension_id)
    next(package_root.glob("*.json")).write_text("tampered")
    from nous_runtime.tools import ToolDefinition

    catalog = ToolCatalog()
    catalog.register(
        ToolDefinition(
            tool_id="host_read",
            description="Read host metadata",
            input_schema={"type": "object"},
            effect_class="read",
        ),
        executor=lambda *_: {"ok": True},
    )
    WorkExtensionTools(
        root, WorkHarness(root).create("Inspect host"), executor=executor
    ).register(catalog)
    unavailable = catalog.discover(category="extension")[0]
    assert unavailable["availability"] == "unavailable"
    assert not catalog.execute(unavailable["tool_id"], {})["ok"]
    assert catalog.execute("host_read", {})["ok"]
    assert not kernel.execution_calls and not adapter.calls

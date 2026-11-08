from __future__ import annotations

from nous_runtime.work import WorkHarness
from nous_runtime.work.components import build_work_components


def test_work_components_load_workspace_providers_before_gateway(tmp_path, monkeypatch):
    harness = WorkHarness(tmp_path)
    snapshot = harness.create(
        "Inspect this workspace, make the smallest correct change, and run tests"
    )
    snapshot.execution_options["model_timeout_s"] = 321.0
    loaded: list[bool] = []
    configured: list[bool] = []
    facade = object()
    gateway_results = iter((None, facade))

    monkeypatch.setattr(
        "nous_runtime.cli.provider_setup.load_providers_from_config",
        lambda workspace: loaded.append(workspace) or 1,
    )
    monkeypatch.setattr(
        "nous_runtime.model_runtime.get_gateway_facade",
        lambda *, required: next(gateway_results),
    )
    monkeypatch.setattr(
        "nous_runtime.model_runtime.factory.gateway_service.configure_from_providers",
        lambda: configured.append(True),
    )

    components = build_work_components(tmp_path, snapshot)

    assert loaded == [tmp_path.resolve()]
    assert configured == [True]
    assert components.deliberator.facade is facade
    assert components.deliberator.timeout_s == 321.0
    assert components.deliberator.max_output_tokens == 1536
    tool_ids = {item["tool_id"] for item in components.tools.discover()}
    assert "run_command" not in tool_ids
    assert "shell_start" not in tool_ids
    assert "propose_files" in tool_ids
    assert not components.tools.execute(
        "shell_start", {"command": ["python", "-m", "pytest"]}
    )["ok"]


def test_work_components_fall_back_to_runtime_provider_workspace(tmp_path, monkeypatch):
    harness = WorkHarness(tmp_path)
    snapshot = harness.create("Inspect this workspace")
    loaded = []
    facade = object()
    gateway_results = iter((None, facade))

    def load(workspace=None):
        loaded.append(workspace)
        return 0 if workspace is not None else 1

    monkeypatch.setattr(
        "nous_runtime.cli.provider_setup.load_providers_from_config", load
    )
    monkeypatch.setattr(
        "nous_runtime.model_runtime.get_gateway_facade",
        lambda *, required: next(gateway_results),
    )
    monkeypatch.setattr(
        "nous_runtime.model_runtime.factory.gateway_service.configure_from_providers",
        lambda: None,
    )

    build_work_components(tmp_path, snapshot)

    assert loaded == [tmp_path.resolve(), None]


def test_work_components_disclose_bounded_write_tools(tmp_path, monkeypatch):
    harness = WorkHarness(tmp_path)
    snapshot = harness.create(
        "Create research-report.md. Do not modify any other file."
    )
    facade = object()

    monkeypatch.setattr(
        "nous_runtime.cli.provider_setup.load_providers_from_config",
        lambda workspace=None: 1,
    )
    monkeypatch.setattr(
        "nous_runtime.model_runtime.get_gateway_facade",
        lambda *, required: facade,
    )

    components = build_work_components(tmp_path, snapshot)
    file_tools = {item["tool_id"] for item in components.tools.expand("files")["tools"]}

    assert "write_file" in file_tools
    assert "patch_file" in file_tools


def test_work_test_identity_is_current_and_never_restored_from_checkpoint(tmp_path):
    from nous_runtime.chat.agent_tools import WorkspaceToolRuntime
    from nous_runtime.governance import AuthorizationContext
    from nous_runtime.tools import ToolCatalog
    from nous_runtime.work import WorkExecutionComponents, WorkSupervisor

    owners = []

    def factory(root, snapshot):
        owner = WorkspaceToolRuntime(
            str(root), allow_mutations=True, source_work_id=snapshot.run_id
        )
        tools = ToolCatalog()
        tools.register_runtime(owner)
        owners.append(owner)
        return WorkExecutionComponents(
            tools=tools,
            deliberator=lambda _: {
                "status": "blocked",
                "summary": "Inspect current identity",
            },
            verifier=None,
        )

    context = AuthorizationContext(
        subject_type="service",
        subject_id="current-work-caller",
        authn_method="opaque_token",
        authn_confidence=0.9,
    )
    host = WorkSupervisor(tmp_path, component_factory=factory)
    try:
        created = host.start("Run project tests", authorization_context=context)
        original = host.wait(created.run_id, timeout=5)
        assert owners[-1].authorization_context == context.to_dict()
        assert "authorization_context" not in original.execution_options
        assert "current-work-caller" not in str(original.to_dict())
    finally:
        host.close()
    restarted = WorkSupervisor(tmp_path, component_factory=factory)
    try:
        restarted.resume(created.run_id)
        restarted.wait(created.run_id, timeout=5)
        assert owners[-1].authorization_context == {}
    finally:
        restarted.close()

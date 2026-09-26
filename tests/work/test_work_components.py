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
    assert components.deliberator.max_output_tokens == 1024
    tool_ids = {item["tool_id"] for item in components.tools.discover()}
    assert "run_command" not in tool_ids
    assert "shell_start" in tool_ids


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

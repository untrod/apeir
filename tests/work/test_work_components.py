from __future__ import annotations

from nous_runtime.work import WorkHarness
from nous_runtime.work.components import build_work_components


def test_work_components_load_workspace_providers_before_gateway(tmp_path, monkeypatch):
    harness = WorkHarness(tmp_path)
    snapshot = harness.create("Inspect this workspace")
    snapshot.execution_options["model_timeout_s"] = 321.0
    loaded: list[bool] = []
    configured: list[bool] = []
    facade = object()
    gateway_results = iter((None, facade))

    monkeypatch.setattr(
        "nous_runtime.cli.provider_setup.load_providers_from_config",
        lambda: loaded.append(True) or 1,
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

    assert loaded == [True]
    assert configured == [True]
    assert components.deliberator.facade is facade
    assert components.deliberator.timeout_s == 321.0
    assert components.deliberator.max_output_tokens == 384

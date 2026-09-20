from __future__ import annotations

import hashlib

import pytest

from nous_runtime.model_distribution import (
    CatalogModel,
    DownloadArtifact,
    InstallerStep,
    ModelCatalog,
    ModelInstallerController,
)
from nous_runtime.model_runtime import (
    HardwareBudget,
    ModelDescriptor,
    ModelEndpointType,
    ModelModality,
    ModelPackage,
    ModelResolutionError,
)


def local_catalog(source) -> ModelCatalog:
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    return ModelCatalog(
        catalog_version="1",
        generated_at="2026-07-26T00:00:00Z",
        signature="test",
        models=(
            CatalogModel(
                descriptor=ModelDescriptor(
                    model_id="local/reasoner",
                    display_name="Reasoner",
                    provider_id="local-imported",
                    endpoint_type=ModelEndpointType.LOCAL_MODEL,
                    capabilities=frozenset({"reasoning"}),
                ),
                packages=(
                    ModelPackage(
                        package_id="reasoner-cpu",
                        model_id="local/reasoner",
                        capabilities=frozenset({"reasoning"}),
                        modalities=frozenset({ModelModality.TEXT}),
                        disk_mb=1,
                    ),
                ),
                artifacts=(
                    DownloadArtifact(
                        artifact_id="reasoner-weights",
                        urls=(str(source),),
                        sha256=checksum,
                        size_bytes=source.stat().st_size,
                        filename="reasoner.gguf",
                    ),
                ),
            ),
        ),
    )


def test_installer_controller_plans_downloads_verifies_and_recovers(
    tmp_path,
) -> None:
    source = tmp_path / "source.gguf"
    source.write_bytes(b"reasoner")
    controller = ModelInstallerController(tmp_path / ".nous")
    controller.prepare()
    controller.select_capabilities(["reasoning"])
    resolution = controller.plan(
        local_catalog(source),
        hardware=HardwareBudget(
            disk_mb=100,
            memory_mb=1024,
            allow_gpu_packages=False,
        ),
    )
    assert resolution.complete
    assert controller.state.selected_packages == ["reasoner-cpu"]
    controller.accept_licenses(["reasoner-cpu"])
    downloaded = controller.download_selected(local_catalog(source))
    assert "reasoner-weights" in downloaded
    assert controller.verify()["ok"] is True

    for step in list(InstallerStep)[1:]:
        controller.advance(step)
    assert controller.state.current_step is InstallerStep.COMPLETE

    recovered = ModelInstallerController(tmp_path / ".nous")
    assert recovered.state.current_step is InstallerStep.COMPLETE
    assert recovered.state.downloaded_files == downloaded


def test_installer_does_not_skip_steps_or_store_raw_secret(tmp_path) -> None:
    controller = ModelInstallerController(tmp_path / ".nous")
    controller.prepare()
    with pytest.raises(ModelResolutionError, match="cannot be skipped"):
        controller.advance(InstallerStep.CAPABILITIES)
    with pytest.raises(ModelResolutionError, match="not raw secrets"):
        controller.set_provider_reference(
            "openai",
            "sk-this-is-a-raw-key",
        )
    controller.set_provider_reference(
        "openai",
        "credential://openai/default",
    )
    assert controller.state.provider_references == {
        "openai": "credential://openai/default"
    }

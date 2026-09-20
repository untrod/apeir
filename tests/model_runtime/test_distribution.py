from __future__ import annotations

import hashlib
import json

import pytest
from typer.testing import CliRunner

from nous_runtime.cli.main import app
from nous_runtime.model_distribution import (
    CatalogModel,
    DownloadArtifact,
    LocalModelImporter,
    ModelCatalog,
    ModelDistributionManager,
    ResumableModelDownloader,
    TransactionJournal,
)
from nous_runtime.model_runtime import (
    ModelDescriptor,
    ModelEndpointType,
    ModelModality,
    ModelPackage,
    ModelResolutionError,
    ModelRuntimeRegistry,
)


def catalog_payload(signature: str = "valid") -> dict[str, object]:
    descriptor = ModelDescriptor(
        model_id="catalog-model",
        display_name="Catalog Model",
        provider_id="local-imported",
        endpoint_type=ModelEndpointType.LOCAL_MODEL,
        capabilities=frozenset({"reasoning"}),
    )
    model = CatalogModel(
        descriptor=descriptor,
        packages=(
            ModelPackage(
                package_id="catalog-model-cpu",
                model_id="catalog-model",
                capabilities=frozenset({"reasoning"}),
                modalities=frozenset({ModelModality.TEXT}),
                disk_mb=10,
            ),
        ),
    )
    return {
        "catalog_version": "1",
        "generated_at": "2026-07-26T00:00:00Z",
        "models": [model.to_dict()],
        "metadata": {},
        "signature": signature,
    }


def test_catalog_requires_and_verifies_signature(tmp_path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(catalog_payload()),
        encoding="utf-8",
    )
    catalog = ModelCatalog.load(
        path,
        verifier=lambda _payload, signature: signature == "valid",
    )
    assert catalog.model("catalog-model") is not None

    with pytest.raises(ModelResolutionError, match="invalid"):
        ModelCatalog.load(
            path,
            verifier=lambda _payload, _signature: False,
        )


def test_download_artifact_rejects_path_traversal() -> None:
    with pytest.raises(ModelResolutionError, match="plain file name"):
        DownloadArtifact(
            artifact_id="unsafe",
            urls=("https://example.invalid/model",),
            sha256="0" * 64,
            size_bytes=1,
            filename="../model.gguf",
        )


def test_downloader_uses_mirror_checksum_and_transaction(tmp_path) -> None:
    source = tmp_path / "source.gguf"
    source.write_bytes(b"verified-model")
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    journal = TransactionJournal(tmp_path / "transactions.json")
    downloader = ResumableModelDownloader(
        tmp_path / "downloads",
        journal=journal,
        chunk_size=4,
    )
    artifact = DownloadArtifact(
        artifact_id="model",
        urls=(
            str(tmp_path / "missing.gguf"),
            str(source),
        ),
        sha256=checksum,
        size_bytes=source.stat().st_size,
        filename="model.gguf",
    )
    result = downloader.download(artifact)
    assert result.read_bytes() == b"verified-model"
    assert journal.incomplete() == []


def test_importer_reference_copy_and_registry_manager(tmp_path) -> None:
    source = tmp_path / "model.gguf"
    source.write_bytes(b"model")
    importer = LocalModelImporter()
    referenced = importer.import_model(source)
    assert referenced.referenced is True
    assert referenced.location == str(source.resolve())

    copied = importer.import_model(
        source,
        destination_root=tmp_path / "copied",
        reference=False,
    )
    assert copied.referenced is False
    assert (tmp_path / "copied" / "model.gguf").is_file()

    registry = ModelRuntimeRegistry(tmp_path / "registry.json")
    imported, record = ModelDistributionManager(registry).import_local(
        source,
        model_id="local/test",
    )
    assert imported.format == "gguf"
    assert record.descriptor.model_id == "local/test"
    assert registry.require("local/test").location == str(source.resolve())


def test_simplified_models_cli_setup_import_and_list(
    tmp_path,
    monkeypatch,
) -> None:
    workspace = tmp_path / ".nous"
    source = tmp_path / "model.gguf"
    source.write_bytes(b"model")
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(workspace))
    runner = CliRunner()

    setup = runner.invoke(app, ["setup", "--path", str(workspace)])
    assert setup.exit_code == 0
    assert "prepared" in setup.stdout

    imported = runner.invoke(
        app,
        [
            "models",
            "import",
            str(source),
            "--model-id",
            "local/cli",
        ],
    )
    assert imported.exit_code == 0
    assert "local/cli" in imported.stdout

    listed = runner.invoke(app, ["models", "list", "--json"])
    assert listed.exit_code == 0
    assert '"model_id": "local/cli"' in listed.stdout

import json
from pathlib import Path

from typer.testing import CliRunner

from nous_runtime.artifact import ArtifactType, ContentAddressedArtifactStore
from nous_runtime.cli.main import app


def test_deploy_cli_apply_status_and_list(tmp_path: Path):
    artifact_root = tmp_path / "artifacts"
    state_dir = tmp_path / "deployments"
    digest = ContentAddressedArtifactStore(artifact_root).store_bytes(
        b"configuration",
        artifact_type=ArtifactType.CONFIGURATION,
        name="config.json",
    )["artifact"]["digest"]
    common = ["--artifact-root", str(artifact_root), "--state-dir", str(state_dir)]
    runner = CliRunner()

    applied = runner.invoke(
        app,
        ["deploy", "apply", digest, "--target", "local", "--deployment-id", "cli-1", *common],
    )
    status = runner.invoke(app, ["deploy", "status", "cli-1", *common])
    listed = runner.invoke(app, ["deploy", "list", *common])

    assert applied.exit_code == 0, applied.output
    assert json.loads(applied.output)["state"] == "ACTIVE"
    assert json.loads(status.output)["deployment_id"] == "cli-1"
    assert json.loads(listed.output)[0]["state"] == "ACTIVE"

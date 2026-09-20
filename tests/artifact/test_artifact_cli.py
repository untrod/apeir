import json
from pathlib import Path

from typer.testing import CliRunner

from nous_runtime.cli.main import app


def test_artifact_cli_add_list_verify_and_safe_gc(tmp_path: Path):
    source = tmp_path / "firmware.bin"
    source.write_bytes(b"firmware")
    root = tmp_path / "store"
    runner = CliRunner()

    added = runner.invoke(
        app,
        ["artifact", "add", str(source), "--type", "firmware", "--root", str(root)],
    )
    assert added.exit_code == 0, added.output
    digest = json.loads(added.output)["artifact"]["digest"]

    listed = runner.invoke(app, ["artifact", "list", "--root", str(root)])
    verified = runner.invoke(
        app, ["artifact", "verify", digest, "--root", str(root)]
    )
    preview = runner.invoke(app, ["artifact", "gc", "--root", str(root)])

    assert json.loads(listed.output)[0]["digest"] == digest
    assert json.loads(verified.output)["verified"] is True
    assert json.loads(preview.output)["dry_run"] is True
    assert root.joinpath("index.json").is_file()

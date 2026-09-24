from __future__ import annotations

import base64
import subprocess

import pytest

from nous_runtime.artifact.models import ArtifactType
from nous_runtime.execution.executables import resolve_executable
from nous_runtime.tools import ArtifactToolRuntime, GitToolRuntime, ToolCatalog


def test_artifact_tools_reuse_workspace_content_store(tmp_path):
    source = tmp_path / "result.txt"
    source.write_text("verified result", encoding="utf-8")
    runtime = ArtifactToolRuntime(tmp_path, allow_mutations=True)

    assert not (tmp_path / ".nous" / "artifacts").exists()
    assert any(
        item["function"]["name"] == "artifact_put" for item in runtime.specifications()
    )
    assert not (tmp_path / ".nous" / "artifacts").exists()

    stored = runtime.execute(
        "artifact_put",
        {
            "path": "result.txt",
            "artifact_type": ArtifactType.REPORT.value,
            "media_type": "text/plain",
        },
    )
    digest = stored["artifact"]["digest"]
    inspected = runtime.execute("artifact_inspect", {"digest": digest})
    loaded = runtime.execute("artifact_get", {"digest": digest})
    listed = runtime.execute("artifact_list", {})

    assert stored["ok"] is True
    assert inspected["ok"] is True
    assert inspected["integrity"] == "verified"
    assert base64.b64decode(loaded["content_base64"]) == b"verified result"
    assert listed["artifacts"][0]["digest"] == digest
    assert stored["receipt"]["requested_capabilities"] == ["artifact.store"]


def test_read_only_artifact_runtime_does_not_advertise_put(tmp_path):
    runtime = ArtifactToolRuntime(tmp_path, allow_mutations=False)

    names = {item["function"]["name"] for item in runtime.specifications()}

    assert "artifact_list" in names
    assert "artifact_put" not in names


@pytest.mark.skipif(resolve_executable("git") is None, reason="git is unavailable")
def test_git_tools_are_fixed_read_only_catalog_entries(tmp_path):
    git = resolve_executable("git")
    subprocess.run(
        [git, "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    (tmp_path / "sample.txt").write_text("value", encoding="utf-8")
    runtime = GitToolRuntime(tmp_path)
    if not runtime.sandbox_available:
        assert runtime.specifications() == ()
        assert runtime.execute("git_status", {})["ok"] is False
        return
    catalog = ToolCatalog()
    catalog.register_runtime(runtime, provider_id="git-sandbox")

    status = catalog.execute("git_status", {})
    definitions = catalog.discover(category="git")

    assert status["ok"] is True
    assert "sample.txt" in status["stdout"]
    assert {item["effect_class"] for item in definitions} == {"read"}
    assert {item["approval_policy"] for item in definitions} == {"none"}

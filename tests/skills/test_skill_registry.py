from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from nous_runtime.skills import SkillRegistry, SkillToolRuntime
from nous_runtime.skills.cli import skill_app


def make_skill(
    root: Path, *, name: str = "code-helper", version: str = "1.2.3"
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        f"version: {version}\n"
        "description: Inspect code with bounded tools.\n"
        "required_capabilities: [filesystem.read]\n"
        "suggested_tools: [read_file, search_workspace]\n"
        "tags: [code, review]\n"
        "risk: low\n"
        "verification: [tests pass, diff reviewed]\n"
        "---\n"
        "Read relevant code before proposing a bounded change.\n",
        encoding="utf-8",
    )
    (root / "references").mkdir(exist_ok=True)
    (root / "references" / "guide.md").write_text("reference", encoding="utf-8")
    (root / "templates").mkdir(exist_ok=True)
    (root / "templates" / "report.md").write_text("template", encoding="utf-8")
    (root / "scripts").mkdir(exist_ok=True)
    (root / "scripts" / "never_run.py").write_text(
        "from pathlib import Path\nPath('executed').write_text('bad')\n",
        encoding="utf-8",
    )
    return root


def test_project_skill_uses_progressive_disclosure(tmp_path: Path):
    source = make_skill(tmp_path / ".nous" / "skills" / "code-helper")
    registry = SkillRegistry(
        tmp_path, builtin_dir=tmp_path / "none", user_dir=tmp_path / "user"
    )

    summary = registry.summaries()[0]
    loaded = registry.load("code-helper")

    assert summary["skill_id"] == "code-helper"
    assert summary["provider"] == "project"
    assert summary["authority"] == "none"
    assert summary["tags"] == ["code", "review"]
    assert summary["requested_capabilities"] == [
        "filesystem.read",
        "process.execute",
        "tool.invoke",
    ]
    assert "instructions" not in summary
    assert "resources" not in summary
    assert loaded.instructions.startswith("Read relevant code")
    assert loaded.resources == (
        "references/guide.md",
        "scripts/never_run.py",
        "templates/report.md",
    )
    assert not (source / "executed").exists()


def test_legacy_json_provider_keeps_compatibility_without_authority(tmp_path: Path):
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    (builtin / "legacy.json").write_text(
        json.dumps(
            {
                "id": "legacy-review",
                "name": "Legacy Review",
                "description": "Review legacy code",
                "triggers": ["review", "legacy"],
                "permissions": ["files.read"],
                "tools": ["file_read"],
                "success_criteria": ["review complete"],
                "instruction": "Inspect before reporting.",
            }
        ),
        encoding="utf-8",
    )
    registry = SkillRegistry(tmp_path, builtin_dir=builtin, user_dir=tmp_path / "user")

    summary = registry.summaries()[0]
    loaded = registry.load("legacy-review")

    assert summary["provider"] == "builtin"
    assert summary["trust"] == "builtin"
    assert summary["authority"] == "none"
    assert summary["tags"] == ["review", "legacy"]
    assert loaded.verification == ("review complete",)
    assert loaded.instructions == "Inspect before reporting."


def test_install_reuses_extension_and_artifact_runtimes_without_executing_scripts(
    tmp_path: Path,
):
    source = make_skill(tmp_path / "source" / "safe-skill", name="safe-skill")
    registry = SkillRegistry(
        tmp_path, builtin_dir=tmp_path / "none", user_dir=tmp_path / "user"
    )

    installed = registry.install(source)

    assert installed.provider == "installed"
    assert installed.installed is True
    assert installed.artifact_ref.startswith("sha256:")
    assert installed.metadata["authority"] == "none"
    assert (
        registry.extensions.verify("skills/safe-skill").skills[0].name == "safe-skill"
    )
    artifact = json.loads(
        (tmp_path / ".nous" / "artifacts" / "index.json").read_text(encoding="utf-8")
    )
    assert installed.artifact_ref in artifact
    assert artifact[installed.artifact_ref]["metadata"]["authority"] == "none"
    assert not (source / "executed").exists()

    registry.disable("safe-skill")
    assert all(item.skill_id != "safe-skill" for item in registry.list())
    assert registry.resolve("safe-skill", include_disabled=True).enabled is False
    registry.enable("safe-skill")
    assert registry.remove("safe-skill") is True
    assert registry.extensions.get("skills/safe-skill") is None
    assert not (source / "executed").exists()


def test_update_replaces_installed_projection_and_artifact_pin(tmp_path: Path):
    source = make_skill(tmp_path / "source" / "safe-skill", name="safe-skill")
    registry = SkillRegistry(
        tmp_path, builtin_dir=tmp_path / "none", user_dir=tmp_path / "user"
    )
    first = registry.install(source)
    (source / "SKILL.md").write_text(
        (source / "SKILL.md")
        .read_text(encoding="utf-8")
        .replace("version: 1.2.3", "version: 1.2.4")
        .replace("bounded change", "verified change"),
        encoding="utf-8",
    )

    second = registry.update(source)

    assert second.version == "1.2.4"
    assert second.artifact_ref != first.artifact_ref
    pins = json.loads(
        (tmp_path / ".nous" / "artifacts" / "pins.json").read_text(encoding="utf-8")
    )
    assert second.artifact_ref in pins
    assert first.artifact_ref not in pins


def test_local_catalog_discovery_does_not_load_instructions(tmp_path: Path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "apeir.skill-catalog/v1",
                "skills": [
                    {
                        "name": "research",
                        "description": "Gather and cross-check evidence",
                        "version": "1.0.0",
                        "source": "https://example.test/research.zip",
                        "digest": "sha256:" + "a" * 64,
                        "tags": ["research", "evidence"],
                        "requested_capabilities": ["network.connect"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    registry = SkillRegistry(
        tmp_path, builtin_dir=tmp_path / "none", user_dir=tmp_path / "user"
    )

    registry.add_catalog(str(catalog))
    result = registry.search("evidence")[0]

    assert result.provider == "catalog"
    assert result.instructions == ""
    assert result.requested_capabilities == ("network.connect",)
    assert registry.catalogs() == (str(catalog),)
    try:
        registry.load("research")
    except ValueError as exc:
        assert "installed before loading" in str(exc)
    else:
        raise AssertionError("catalog-only Skill was loaded")


def test_skill_tool_runtime_and_cli_expose_summaries_then_load(tmp_path: Path):
    make_skill(tmp_path / ".nous" / "skills" / "code-helper")
    runtime = SkillToolRuntime(tmp_path)

    listed = runtime.execute("skill_list", {})
    loaded = runtime.execute("skill_load", {"skill_id": "code-helper"})
    cli = CliRunner().invoke(
        skill_app,
        ["list", "--root", str(tmp_path), "--json"],
    )

    assert listed["ok"] is True
    assert "instructions" not in listed["skills"][0]
    assert loaded["skill"]["instructions"].startswith("Read relevant code")
    assert cli.exit_code == 0
    assert '"skill_id": "code-helper"' in cli.stdout

"""Reviewed local catalogs publish through the existing Extension/CAS stores."""

import json
import zipfile

import pytest

from nous_runtime.artifact import ContentAddressedArtifactStore
from nous_runtime.skills import SkillRegistry, SkillToolRuntime
from tests.skills.test_skill_registry import make_skill


def catalog(tmp_path):
    source = make_skill(tmp_path / "catalog" / "code-helper")
    registry = SkillRegistry(tmp_path / "workspace")
    registry.add_catalog(str(source.parent))
    return registry, source, registry.catalog_records()[0]


def install(registry, entry, **kwargs):
    return registry.install_from_catalog(
        entry.skill_id,
        catalog_source=entry.metadata["catalog_source"],
        version=entry.version,
        digest=entry.digest,
        **kwargs,
    )


def test_catalog_install_update_disabled_restart_and_remove(tmp_path):
    registry, source, entry = catalog(tmp_path)
    first = install(registry, entry)
    assert first.artifact_ref and first.digest == entry.digest
    assert (
        registry.extensions.get_record("skills/code-helper")["artifact_ref"]
        == first.artifact_ref
    )
    assert not (source / "executed").exists()
    assert not SkillToolRuntime(registry.workspace).execute("process.execute", {})["ok"]
    registry.disable("installed:code-helper")
    (source / "SKILL.md").write_text(
        (source / "SKILL.md").read_text().replace("1.2.3", "1.2.4")
    )
    second = install(registry, registry.catalog_records()[0])
    assert not second.enabled and second.version == "1.2.4"
    restarted = SkillRegistry(registry.workspace)
    assert not SkillToolRuntime(registry.workspace).execute(
        "skill_load", {"skill_id": "installed:code-helper"}
    )["ok"]
    restarted.enable("installed:code-helper")
    assert restarted.load("installed:code-helper").artifact_ref == second.artifact_ref
    assert restarted.remove("installed:code-helper")
    assert not SkillRegistry(registry.workspace).extensions.list()
    assert not (source / "executed").exists()


def test_catalog_changed_after_review_cannot_replace_valid_install(tmp_path):
    registry, source, entry = catalog(tmp_path)
    first = install(registry, entry)
    (source / "SKILL.md").write_text((source / "SKILL.md").read_text() + "tampered")
    with pytest.raises(ValueError, match="changed"):
        install(registry, entry)
    assert registry.load("installed:code-helper").digest == first.digest


def test_cas_failure_does_not_publish_replacement(tmp_path, monkeypatch):
    registry, source, entry = catalog(tmp_path)
    first = install(registry, entry)
    (source / "SKILL.md").write_text(
        (source / "SKILL.md").read_text().replace("1.2.3", "1.2.4")
    )

    def fail(*args, **kwargs):
        raise OSError("deterministic CAS failure")

    monkeypatch.setattr(ContentAddressedArtifactStore, "store_bytes", fail)
    with pytest.raises(OSError, match="CAS failure"):
        install(registry, registry.catalog_records()[0])
    assert registry.load("installed:code-helper").digest == first.digest
    assert registry.extensions.verify("skills/code-helper").version == "1.2.3"


def test_failed_index_publication_restores_previous_install(tmp_path, monkeypatch):
    registry, source, entry = catalog(tmp_path)
    first = install(registry, entry)
    prior = {
        path: path.read_bytes()
        for path in (registry.extensions.index_path, registry.extensions.lock_path)
    }
    (source / "SKILL.md").write_text(
        (source / "SKILL.md").read_text().replace("1.2.3", "1.2.4")
    )

    def fail(*args):
        raise OSError("deterministic lock publication failure")

    monkeypatch.setattr(registry.extensions, "_write_lock", fail)
    with pytest.raises(OSError, match="publication failure"):
        install(registry, registry.catalog_records()[0])
    assert all(path.read_bytes() == content for path, content in prior.items())
    assert registry.load("installed:code-helper").digest == first.digest


def test_post_acquisition_admission_failure_keeps_existing_install(tmp_path):
    registry, source, entry = catalog(tmp_path)
    first = install(registry, entry)
    (source / "SKILL.md").write_text(
        (source / "SKILL.md").read_text().replace("1.2.3", "1.2.4")
    )

    def deny():
        raise PermissionError("human session revoked during acquisition")

    with pytest.raises(PermissionError, match="revoked"):
        install(registry, registry.catalog_records()[0], before_publish=deny)
    assert registry.load("installed:code-helper").digest == first.digest


@pytest.mark.parametrize(
    "source", ["../outside/code-helper", "https://example.test/package.zip"]
)
def test_catalog_cannot_install_outside_registered_local_directory(tmp_path, source):
    registry, _, entry = catalog(tmp_path)
    path = tmp_path / "catalog" / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "schema": "apeir.skill-catalog/v1",
                "skills": [
                    {
                        "name": entry.skill_id,
                        "description": entry.description,
                        "version": entry.version,
                        "digest": entry.digest,
                        "source": source,
                    }
                ],
            }
        )
    )
    registry.remove_catalog(str(path.parent))
    registry.add_catalog(str(path))
    with pytest.raises((PermissionError, ValueError)):
        install(registry, registry.catalog_records()[0])
    assert not registry.extensions.list()


def test_unregistered_and_duplicate_entries_fail_closed(tmp_path):
    registry, _, entry = catalog(tmp_path)
    registry.remove_catalog(entry.metadata["catalog_source"])
    with pytest.raises(PermissionError):
        install(registry, entry)
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "schema": "apeir.skill-catalog/v1",
                "skills": [
                    {
                        "name": "one",
                        "description": "one",
                        "version": "1",
                        "digest": entry.digest,
                    },
                ]
                * 2,
            }
        )
    )
    registry.add_catalog(str(path))
    with pytest.raises(ValueError, match="ambiguous"):
        install(registry, registry.catalog_records()[0])


def test_declared_trust_does_not_become_verified_identity(tmp_path):
    registry = SkillRegistry(tmp_path)
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "schema": "apeir.skill-catalog/v1",
                "skills": [
                    {
                        "name": "one",
                        "description": "one",
                        "version": "1",
                        "trust": "verified",
                    }
                ],
            }
        )
    )
    registry.add_catalog(str(path))
    assert registry.catalog_records()[0].trust == "unverified"


def test_oversized_entry_count_and_unsafe_zip_do_not_publish(tmp_path):
    registry = SkillRegistry(tmp_path)
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps({"schema": "apeir.skill-catalog/v1", "skills": [{}] * 513})
    )
    with pytest.raises(ValueError, match="512"):
        registry.add_catalog(str(path))
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../escape", "bad")
    with pytest.raises(ValueError):
        registry.install(archive)
    assert not registry.extensions.list()
    assert not (tmp_path.parent / "escape").exists()


def test_cas_evidence_tampering_hides_skill_instead_of_loading_it(tmp_path):
    registry, _, entry = catalog(tmp_path)
    record = install(registry, entry)
    store = ContentAddressedArtifactStore(registry.artifact_root)
    blob = store.resolve(record.artifact_ref)
    blob.write_bytes(b"tampered")
    with pytest.raises(KeyError):
        registry.load("installed:code-helper")
    assert any("integrity" in row["error"] for row in registry.diagnostics)


def test_revoked_extension_cannot_load_or_reinstall_through_catalog(tmp_path):
    registry, _, entry = catalog(tmp_path)
    install(registry, entry)
    index = json.loads(registry.extensions.index_path.read_text())
    index["extensions"]["skills/code-helper"]["state"] = "revoked"
    registry.extensions.index_path.write_text(json.dumps(index))
    with pytest.raises(KeyError):
        registry.load("installed:code-helper")
    with pytest.raises(PermissionError, match="Revoked"):
        install(registry, entry)
    assert (
        SkillRegistry(registry.workspace).extensions.get_record("skills/code-helper")[
            "state"
        ]
        == "revoked"
    )

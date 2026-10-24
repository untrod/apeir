"""Skill publication owns only its own retention in the authoritative CAS."""

import json

import pytest

from nous_runtime.artifact import ContentAddressedArtifactStore
from nous_runtime.skills import SkillRegistry
from tests.skills.test_catalog_installation import catalog, install
from tests.skills.test_skill_registry import make_skill


@pytest.mark.parametrize("fault", ["approval", "publication"])
def test_failed_skill_update_releases_only_its_preparation_hold(
    tmp_path, monkeypatch, fault
):
    registry, source, entry = catalog(tmp_path)
    first = install(registry, entry)
    store = ContentAddressedArtifactStore(registry.artifact_root)
    before = store.pins_path.read_bytes()
    path = source / "SKILL.md"
    path.write_text(path.read_text().replace("1.2.3", "1.2.4"))

    def deny(*args):
        raise PermissionError("owned update failure")

    kwargs = {"before_publish": deny} if fault == "approval" else {}
    if fault == "publication":
        monkeypatch.setattr(registry.extensions, "_write_lock", deny)
    with pytest.raises(PermissionError, match="owned update failure"):
        install(registry, registry.catalog_records()[0], **kwargs)
    assert store.pins_path.read_bytes() == before
    assert registry.load("installed:code-helper").artifact_ref == first.artifact_ref
    assert len(store.garbage_collect()["candidates"]) == 1


def test_catalog_update_then_uninstall_releases_owned_retention_after_restart(tmp_path):
    registry, source, entry = catalog(tmp_path)
    first = install(registry, entry)
    path = source / "SKILL.md"
    path.write_text(path.read_text().replace("1.2.3", "1.2.4"))
    second = install(registry, registry.catalog_records()[0])
    store = ContentAddressedArtifactStore(registry.artifact_root)
    assert first.artifact_ref in store.garbage_collect()["candidates"]
    assert second.artifact_ref in store.garbage_collect()["protected"]
    restarted = SkillRegistry(registry.workspace)
    assert restarted.remove("installed:code-helper")
    assert not json.loads(store.pins_path.read_text())
    assert set(store.garbage_collect(dry_run=False)["removed"]) == {
        first.artifact_ref,
        second.artifact_ref,
    }


def test_skill_reinstall_and_remove_preserve_explicit_user_retention(tmp_path):
    registry, _, entry = catalog(tmp_path)
    first = install(registry, entry)
    store = ContentAddressedArtifactStore(registry.artifact_root)
    store.pin(first.artifact_ref, "explicit user retention")
    install(registry, entry)
    registry.remove("installed:code-helper")
    assert "explicit user retention" in store.pins_path.read_text()
    assert not store.garbage_collect(dry_run=False)["removed"]
    assert store.verify(first.artifact_ref)


def test_independent_registry_removal_cannot_collect_shared_cas_skill(tmp_path):
    source = make_skill(tmp_path / "source" / "code-helper")
    shared = tmp_path / "shared-cas"
    first = SkillRegistry(tmp_path / "first", artifact_root=shared)
    second = SkillRegistry(tmp_path / "second", artifact_root=shared)
    a = first.install(source)
    b = second.install(source)
    assert a.artifact_ref == b.artifact_ref
    first.remove("installed:code-helper")
    store = ContentAddressedArtifactStore(shared)
    assert not store.garbage_collect(dry_run=False)["removed"]
    restarted = SkillRegistry(second.workspace, artifact_root=shared)
    assert restarted.load("installed:code-helper").artifact_ref == b.artifact_ref
    restarted.remove("installed:code-helper")
    assert b.artifact_ref in store.garbage_collect(dry_run=False)["removed"]


def test_ambiguous_legacy_skill_pin_is_not_guessed_away(tmp_path):
    registry, _, entry = catalog(tmp_path)
    first = install(registry, entry)
    store = ContentAddressedArtifactStore(registry.artifact_root)
    store.pins_path.write_text(
        json.dumps(
            {
                first.artifact_ref: {
                    "reason": "installed-skill:skills/code-helper",
                    "pinned_at": "legacy",
                }
            }
        )
    )
    install(registry, entry)
    registry.remove("installed:code-helper")
    assert first.artifact_ref in store.garbage_collect()["protected"]


def test_promotion_failure_keeps_published_content_protected(tmp_path, monkeypatch):
    registry, _, entry = catalog(tmp_path)
    original_pin = ContentAddressedArtifactStore.pin
    installed_owner = registry._retention_owner("skills/code-helper")

    def fail_promotion(self, digest, reason="user", *, owner=None):
        if owner == installed_owner:
            raise OSError("owned installed-retention failure")
        return original_pin(self, digest, reason, owner=owner)

    monkeypatch.setattr(ContentAddressedArtifactStore, "pin", fail_promotion)
    with pytest.raises(OSError, match="installed-retention failure"):
        install(registry, entry)
    restarted = SkillRegistry(registry.workspace)
    record = restarted.load("installed:code-helper")
    store = ContentAddressedArtifactStore(registry.artifact_root)
    assert store.verify(record.artifact_ref)
    assert record.artifact_ref in store.garbage_collect()["protected"]
    owners = json.loads(store.pins_path.read_text())[record.artifact_ref]["owners"]
    assert len(owners) == 1 and installed_owner not in owners
    assert str(registry.extensions.root) not in store.pins_path.read_text()


def test_corrupt_retention_blocks_update_without_overwriting_original_install(tmp_path):
    from nous_runtime.core.errors import ArtifactError

    registry, source, entry = catalog(tmp_path)
    first = install(registry, entry)
    store = ContentAddressedArtifactStore(registry.artifact_root)
    before_index = registry.extensions.index_path.read_bytes()
    corrupt = json.dumps(
        {first.artifact_ref: {"reason": "retained", "pinned_at": "now", "owners": {}}}
    )
    store.pins_path.write_text(corrupt)
    path = source / "SKILL.md"
    path.write_text(path.read_text().replace("1.2.3", "1.2.4"))
    with pytest.raises(ArtifactError, match="owners"):
        install(registry, registry.catalog_records()[0])
    assert registry.extensions.index_path.read_bytes() == before_index
    assert store.pins_path.read_text() == corrupt
    assert store._object_path(first.artifact_ref).is_file()


def test_same_thread_registry_callback_reuses_canonical_lifecycle_fence(tmp_path):
    registry, source, entry = catalog(tmp_path)
    first = install(registry, entry)
    actor = SkillRegistry(registry.workspace)
    path = source / "SKILL.md"
    path.write_text(path.read_text().replace("1.2.3", "1.2.4"))
    install(
        registry,
        registry.catalog_records()[0],
        before_publish=lambda: actor.disable("installed:code-helper"),
    )
    updated = actor.resolve("installed:code-helper", include_disabled=True)
    assert updated.version == "1.2.4" and not updated.enabled
    store = ContentAddressedArtifactStore(registry.artifact_root)
    assert first.artifact_ref in store.garbage_collect()["candidates"]


def test_stale_legacy_artifact_projection_cannot_shadow_verified_removal(tmp_path):
    registry, source, entry = catalog(tmp_path)
    first = install(registry, entry)
    state = registry._state()
    state["installed_artifacts"] = {"skills/code-helper": first.artifact_ref}
    registry._write_state(state)
    path = source / "SKILL.md"
    path.write_text(path.read_text().replace("1.2.3", "1.2.4"))
    second = install(registry, registry.catalog_records()[0])
    assert registry.load("installed:code-helper").artifact_ref == second.artifact_ref
    registry.remove("installed:code-helper")
    store = ContentAddressedArtifactStore(registry.artifact_root)
    assert not json.loads(store.pins_path.read_text())
    assert set(store.garbage_collect()["candidates"]) == {
        first.artifact_ref,
        second.artifact_ref,
    }
    assert not registry._state()["installed_artifacts"]

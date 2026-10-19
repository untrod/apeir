"""CAS retention belongs to individual callers, not the last pin writer."""

import json

import pytest

from nous_runtime.artifact import ContentAddressedArtifactStore
from nous_runtime.core.errors import ArtifactError


def artifact(tmp_path):
    store = ContentAddressedArtifactStore(tmp_path)
    digest = store.store_bytes(
        b"shared evidence", artifact_type="evidence", name="shared"
    )["artifact"]["digest"]
    return store, digest


def test_scoped_retention_preserves_another_owner_and_default_user(tmp_path):
    first, digest = artifact(tmp_path)
    second = ContentAddressedArtifactStore(tmp_path)
    first.pin(digest, "human retention")
    first.pin(digest, "installation A", owner="a" * 64)
    second.pin(digest, "installation B", owner="b" * 64)
    first.unpin(digest, owner="a" * 64)
    second.unpin(digest, owner="b" * 64)
    assert digest in second.garbage_collect()["protected"]
    assert "human retention" in first.pins_path.read_text()
    first.unpin(digest)
    assert digest in second.garbage_collect(dry_run=False)["removed"]


def test_default_unpin_cannot_remove_component_retention_after_restart(tmp_path):
    store, digest = artifact(tmp_path)
    store.pin(digest, "component retention", owner="a" * 64)
    restarted = ContentAddressedArtifactStore(tmp_path)
    restarted.unpin(digest)
    assert digest in restarted.garbage_collect()["protected"]
    restarted.unpin(digest, owner="b" * 64)
    assert digest in restarted.garbage_collect()["protected"]
    restarted.unpin(digest, owner="a" * 64)
    assert digest in restarted.garbage_collect()["candidates"]


def test_legacy_pin_is_preserved_when_component_hold_is_released(tmp_path):
    store, digest = artifact(tmp_path)
    legacy = {
        digest: {"reason": "historical retention", "pinned_at": "2026-01-01T00:00:00Z"}
    }
    store.pins_path.write_text(json.dumps(legacy))
    store.pin(digest, "component retention", owner="a" * 64)
    store.unpin(digest, owner="a" * 64)
    assert digest in store.garbage_collect()["protected"]
    assert "historical retention" in store.pins_path.read_text()


@pytest.mark.parametrize("owner", ["", "private/path", "A" * 64, "a" * 65, True, 1])
def test_pin_owner_cannot_contain_unbounded_or_sensitive_identity(tmp_path, owner):
    store, digest = artifact(tmp_path)
    before = store.pins_path.read_bytes() if store.pins_path.exists() else None
    for operation in (store.pin, store.unpin):
        with pytest.raises(ArtifactError):
            operation(digest, owner=owner)
    assert (
        store.pins_path.read_bytes() if store.pins_path.exists() else None
    ) == before


@pytest.mark.parametrize(
    "owners",
    [
        None,
        {},
        {"bad/path": {}},
        {"a" * 64: None},
        {"a" * 64: {"reason": "x", "pinned_at": ""}},
    ],
)
def test_corrupt_scoped_pins_block_mutation_and_gc_without_repair(tmp_path, owners):
    store, digest = artifact(tmp_path)
    corrupt = json.dumps(
        {
            "schema": "apeir.cas-pins/v2",
            digest: {"reason": "x", "pinned_at": "now", "owners": owners},
        }
    )
    store.pins_path.write_text(corrupt)
    for operation in (
        lambda: store.pin(digest, owner="a" * 64),
        lambda: store.unpin(digest, owner="a" * 64),
        lambda: store.garbage_collect(dry_run=False),
    ):
        with pytest.raises(ArtifactError):
            operation()
        assert store.pins_path.read_text() == corrupt
        assert store._object_path(digest).read_bytes() == b"shared evidence"


def test_distinct_instances_concurrently_retain_and_release_same_digest(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    store, digest = artifact(tmp_path)
    owners = [f"{index:064x}" for index in range(8)]

    def retain(owner):
        ContentAddressedArtifactStore(tmp_path).pin(
            digest, "independent caller", owner=owner
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(retain, owners))
    persisted = json.loads(store.pins_path.read_text())[digest]
    assert set(persisted["owners"]) == set(owners)
    for owner in owners[:-1]:
        ContentAddressedArtifactStore(tmp_path).unpin(digest, owner=owner)
    assert digest in store.garbage_collect()["protected"]
    store.unpin(digest, owner=owners[-1])
    assert digest in store.garbage_collect()["candidates"]


def test_registered_sensitive_value_cannot_be_used_as_a_pin_identity(tmp_path):
    import hashlib

    from nous_runtime.core.redaction import register_sensitive_value

    store, digest = artifact(tmp_path)
    fake_material = hashlib.sha256(b"owned fake pin credential material").hexdigest()
    register_sensitive_value(fake_material)
    with pytest.raises(ArtifactError, match="opaque SHA-256"):
        store.pin(digest, owner=fake_material)
    assert not store.pins_path.exists()


@pytest.mark.parametrize("schema", [None, "", "apeir.cas-pins/v999", "missing"])
def test_owned_pins_require_the_known_schema_before_mutation(tmp_path, schema):
    store, digest = artifact(tmp_path)
    store.pin(digest, owner="a" * 64)
    document = json.loads(store.pins_path.read_text())
    assert document["schema"] == "apeir.cas-pins/v2"
    if schema == "missing":
        document.pop("schema")
    else:
        document["schema"] = schema
    corrupted = json.dumps(document)
    store.pins_path.write_text(corrupted)
    for operation in (
        lambda: store.pin(digest),
        lambda: store.unpin(digest),
        lambda: store.garbage_collect(dry_run=False),
    ):
        with pytest.raises(ArtifactError, match="schema"):
            operation()
        assert store.pins_path.read_text() == corrupted
        assert store._object_path(digest).read_bytes() == b"shared evidence"


def test_owned_document_refuses_the_legacy_digest_only_loader(tmp_path):
    from nous_runtime.artifact.content_store import _digest_hex

    store, digest = artifact(tmp_path)
    store.pin(digest, owner="a" * 64)
    original = store.pins_path.read_bytes()
    # Frozen v1 _load_pins validates every top-level key as an artifact digest
    # before pin/unpin/GC writes anything. The schema sentinel must fail this
    # existing validation instead of allowing an old writer to drop owners.
    with pytest.raises(ArtifactError):
        for candidate, record in json.loads(original).items():
            _digest_hex(candidate)
            assert isinstance(record, dict)
    assert store.pins_path.read_bytes() == original
    assert store.verify(digest)

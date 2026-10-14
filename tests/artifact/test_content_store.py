from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from nous_runtime.artifact import ArtifactType, ContentAddressedArtifactStore
from nous_runtime.core.errors import ArtifactError


def test_existing_instances_preserve_each_others_evidence_index(tmp_path):
    first = ContentAddressedArtifactStore(tmp_path)
    second = ContentAddressedArtifactStore(tmp_path)
    original = first.store_bytes(
        b"original observation", artifact_type="evidence", name="original"
    )
    later = second.store_bytes(
        b"later verification", artifact_type="verification_result", name="later"
    )
    reloaded = ContentAddressedArtifactStore(tmp_path)
    assert reloaded.verify(original["artifact"]["digest"])
    assert reloaded.verify(later["artifact"]["digest"])
    dependent = first.store_bytes(
        b"dependent evidence",
        artifact_type="evidence",
        name="dependent",
        depends_on=(later["artifact"]["digest"],),
    )
    assert ContentAddressedArtifactStore(tmp_path).verify(
        dependent["artifact"]["digest"]
    )


def test_concurrent_instances_preserve_original_metadata_and_all_digests(tmp_path):
    stores = [ContentAddressedArtifactStore(tmp_path) for _ in range(8)]
    ready = Barrier(len(stores))

    def write(index):
        ready.wait(timeout=5)
        return stores[index].store_bytes(
            str(index).encode(),
            artifact_type="evidence",
            name=f"evidence-{index}",
            produced_by=f"original-{index}",
        )

    with ThreadPoolExecutor(max_workers=len(stores)) as executor:
        results = list(executor.map(write, range(len(stores))))
    reloaded = ContentAddressedArtifactStore(tmp_path)
    assert len(reloaded.list()) == len(stores)
    for index, result in enumerate(results):
        digest = result["artifact"]["digest"]
        assert reloaded.verify(digest)
        duplicate = stores[(index + 1) % len(stores)].store_bytes(
            str(index).encode(),
            artifact_type="evidence",
            name="replacement",
            produced_by="cannot-replace-provenance",
        )
        assert duplicate["artifact"] == result["artifact"]
        assert duplicate["receipt"]["result"] == "UNCHANGED"


def test_stale_writer_does_not_replace_a_corrupt_persisted_index(tmp_path):
    store = ContentAddressedArtifactStore(tmp_path)
    store.index_path.write_text('{"sha256:invalid": {}}', encoding="utf-8")
    with pytest.raises(ArtifactError):
        store.store_bytes(b"new evidence", artifact_type="evidence", name="new")
    assert store.index_path.read_text(encoding="utf-8") == '{"sha256:invalid": {}}'
    assert not list(store.objects.rglob("*"))


def test_stale_pin_and_gc_preserve_other_instances_protected_evidence(tmp_path):
    writer = ContentAddressedArtifactStore(tmp_path)
    dependency = writer.store_bytes(b"input", artifact_type="evidence", name="input")
    dependent = writer.store_bytes(
        b"result",
        artifact_type="evidence",
        name="result",
        depends_on=(dependency["artifact"]["digest"],),
    )
    separate = writer.store_bytes(b"other", artifact_type="evidence", name="other")
    first = ContentAddressedArtifactStore(tmp_path)
    second = ContentAddressedArtifactStore(tmp_path)
    collector = ContentAddressedArtifactStore(tmp_path)
    first.pin(dependent["artifact"]["digest"], "original result")
    second.pin(separate["artifact"]["digest"], "other result")
    result = collector.garbage_collect(dry_run=False)
    assert result["removed"] == []
    assert set(result["protected"]) == {
        item["artifact"]["digest"] for item in (dependency, dependent, separate)
    }
    reloaded = ContentAddressedArtifactStore(tmp_path)
    assert all(
        reloaded.verify(item["artifact"]["digest"])
        for item in (dependency, dependent, separate)
    )


def test_stale_pin_and_unpin_use_current_artifact_and_pin_state(tmp_path):
    stale = ContentAddressedArtifactStore(tmp_path)
    writer = ContentAddressedArtifactStore(tmp_path)
    keep = writer.store_bytes(b"keep", artifact_type="evidence", name="keep")
    remove = writer.store_bytes(b"remove", artifact_type="evidence", name="remove")
    writer.pin(keep["artifact"]["digest"], "must survive")
    stale.pin(remove["artifact"]["digest"], "temporary")
    writer.unpin(remove["artifact"]["digest"])
    result = stale.garbage_collect(dry_run=False)
    assert result["removed"] == [remove["artifact"]["digest"]]
    assert result["protected"] == [keep["artifact"]["digest"]]
    assert ContentAddressedArtifactStore(tmp_path).verify(keep["artifact"]["digest"])


@pytest.mark.parametrize("operation", ("pin", "unpin", "garbage_collect"))
@pytest.mark.parametrize("invalid_entry", ("digest", "record"))
def test_corrupt_pins_block_stale_mutations_without_replacing_evidence(
    tmp_path, operation, invalid_entry
):
    store = ContentAddressedArtifactStore(tmp_path)
    record = store.store_bytes(b"preserve", artifact_type="evidence", name="preserve")
    digest = record["artifact"]["digest"]
    before = store.index_path.read_bytes()
    corrupt = (
        '{"not-a-digest": {}}'
        if invalid_entry == "digest"
        else '{"' + digest + '": null}'
    )
    store.pins_path.write_text(corrupt, encoding="utf-8")
    with pytest.raises(ArtifactError):
        if operation == "garbage_collect":
            store.garbage_collect(dry_run=False)
        else:
            getattr(store, operation)(digest)
    assert store.pins_path.read_text(encoding="utf-8") == corrupt
    assert store.index_path.read_bytes() == before
    assert store.resolve(digest).read_bytes() == b"preserve"


def test_pin_reason_uses_the_existing_sensitive_data_redactor(tmp_path):
    from nous_runtime.core.redaction import register_sensitive_value

    fake_value = "test-cas-pin-sensitive-value"
    register_sensitive_value(fake_value)
    store = ContentAddressedArtifactStore(tmp_path)
    record = store.store_bytes(b"safe", artifact_type="evidence", name="safe")
    store.pin(record["artifact"]["digest"], f"description {fake_value}")
    persisted = store.pins_path.read_text(encoding="utf-8")
    assert fake_value not in persisted
    assert "description" in persisted
    assert "description <REDACTED>" in persisted


@pytest.mark.parametrize("field", ["media_type", "deployed_to"])
def test_protected_typed_metadata_is_rejected_before_artifact_publication(
    tmp_path, field
):
    from nous_runtime.core.redaction import register_sensitive_value

    fake_value = "test-cas-protected-metadata-value"
    register_sensitive_value(fake_value)
    store = ContentAddressedArtifactStore(tmp_path)
    fields = {
        "media_type": f"text/plain; label={fake_value}",
        "deployed_to": (f"device/{fake_value}",),
    }
    with pytest.raises(ArtifactError, match="typed artifact metadata") as failure:
        store.store_bytes(
            b"safe content",
            artifact_type="evidence",
            name="safe",
            **{field: fields[field]},
        )
    assert fake_value not in str(failure.value)
    assert not store.list()
    assert not store.index_path.exists()
    assert not store.receipts_path.exists()
    assert not list(store.objects.rglob("*.tmp"))
    assert not [path for path in store.objects.rglob("*") if path.is_file()]


def test_store_resolve_deduplicate_and_verify(tmp_path: Path):
    store = ContentAddressedArtifactStore(tmp_path / "store")
    first = store.store_bytes(
        b"firmware-v1", artifact_type=ArtifactType.FIRMWARE, name="board.bin"
    )
    duplicate = store.store_bytes(
        b"firmware-v1", artifact_type=ArtifactType.FIRMWARE, name="board.bin"
    )
    digest = first["artifact"]["digest"]

    assert digest.startswith("sha256:")
    assert first["receipt"]["result"] == "COMPLETED"
    assert duplicate["receipt"]["result"] == "UNCHANGED"
    assert store.resolve(digest).read_bytes() == b"firmware-v1"
    assert store.verify(digest) is True


def test_tamper_detection_is_fail_closed(tmp_path: Path):
    store = ContentAddressedArtifactStore(tmp_path / "store")
    operation = store.store_bytes(
        b"model", artifact_type=ArtifactType.MODEL, name="model.onnx"
    )
    digest = operation["artifact"]["digest"]
    store.resolve(digest).write_bytes(b"tampered")

    assert store.verify(digest) is False
    with pytest.raises(ArtifactError, match="integrity"):
        store.resolve(digest)


def test_artifact_graph_pin_and_transitive_gc(tmp_path: Path):
    store = ContentAddressedArtifactStore(tmp_path / "store")
    source = store.store_bytes(
        b"source", artifact_type=ArtifactType.SOURCE_BUNDLE, name="source.zip"
    )["artifact"]["digest"]
    model = store.store_bytes(
        b"model",
        artifact_type=ArtifactType.MODEL,
        name="model.onnx",
        derived_from=[source],
    )["artifact"]["digest"]
    unused = store.store_bytes(
        b"unused", artifact_type=ArtifactType.REPORT, name="unused.txt"
    )["artifact"]["digest"]
    store.pin(model, "deployment")

    preview = store.garbage_collect()
    assert preview["dry_run"] is True
    assert preview["candidates"] == [unused]
    assert store.get(unused) is not None

    result = store.garbage_collect(dry_run=False)

    assert result["removed"] == [unused]
    assert set(result["protected"]) == {source, model}
    assert store.verify(source)
    assert store.verify(model)
    assert store.get(unused) is None


def test_missing_graph_reference_and_invalid_digest_are_rejected(tmp_path: Path):
    store = ContentAddressedArtifactStore(tmp_path / "store")
    with pytest.raises(ArtifactError, match="reference not found"):
        store.store_bytes(
            b"derived",
            artifact_type=ArtifactType.BINARY,
            name="derived.bin",
            depends_on=["sha256:" + "0" * 64],
        )
    with pytest.raises(ArtifactError, match="digest"):
        store.resolve("../escape")


def test_fetch_from_store_verifies_and_caches_content(tmp_path: Path):
    origin = ContentAddressedArtifactStore(tmp_path / "origin")
    cache = ContentAddressedArtifactStore(tmp_path / "cache")
    digest = origin.store_bytes(
        b"dataset-snapshot",
        artifact_type=ArtifactType.DATASET,
        name="dataset.tar",
        produced_by="capture-job",
    )["artifact"]["digest"]

    fetched = cache.fetch_from_store(origin, digest)

    assert fetched["artifact"]["digest"] == digest
    assert fetched["receipt"]["result"] == "COMPLETED"
    assert cache.resolve(digest).read_bytes() == b"dataset-snapshot"

    origin.resolve(digest).write_bytes(b"tampered")
    with pytest.raises(ArtifactError, match="integrity"):
        ContentAddressedArtifactStore(tmp_path / "empty").fetch_from_store(
            origin, digest
        )


def test_fetch_recursively_caches_artifact_graph(tmp_path: Path):
    origin = ContentAddressedArtifactStore(tmp_path / "origin")
    cache = ContentAddressedArtifactStore(tmp_path / "cache")
    source = origin.store_bytes(
        b"source", artifact_type=ArtifactType.SOURCE_BUNDLE, name="source.zip"
    )["artifact"]["digest"]
    binary = origin.store_bytes(
        b"binary",
        artifact_type=ArtifactType.BINARY,
        name="app.exe",
        depends_on=[source],
    )["artifact"]["digest"]

    cache.fetch_from_store(origin, binary)

    assert cache.verify(source)
    assert cache.verify(binary)


@pytest.mark.parametrize("operation", ["get", "list", "verify", "resolve"])
def test_existing_reader_observes_evidence_published_by_another_store(
    tmp_path, operation
):
    reader = ContentAddressedArtifactStore(tmp_path)
    writer = ContentAddressedArtifactStore(tmp_path)
    published = writer.store_bytes(
        b"fresh independent evidence", artifact_type="evidence", name="fresh"
    )
    digest = published["artifact"]["digest"]
    if operation == "get":
        assert reader.get(digest).digest == digest
    elif operation == "list":
        assert [item.digest for item in reader.list()] == [digest]
    elif operation == "verify":
        assert reader.verify(digest)
    else:
        assert reader.resolve(digest).read_bytes() == b"fresh independent evidence"


@pytest.mark.parametrize("operation", ["get", "list", "verify", "resolve"])
def test_persisted_index_corruption_cannot_be_hidden_by_reader_cache(
    tmp_path, operation
):
    writer = ContentAddressedArtifactStore(tmp_path)
    original = writer.store_bytes(
        b"original", artifact_type="evidence", name="original"
    )
    reader = ContentAddressedArtifactStore(tmp_path)
    digest = original["artifact"]["digest"]
    assert reader.verify(digest)
    damaged = '{"sha256:invalid": {}}'
    writer.index_path.write_text(damaged, encoding="utf-8")
    with pytest.raises(ArtifactError):
        if operation == "list":
            reader.list()
        else:
            getattr(reader, operation)(digest)
    assert writer.index_path.read_text(encoding="utf-8") == damaged
    assert writer._object_path(digest).read_bytes() == b"original"

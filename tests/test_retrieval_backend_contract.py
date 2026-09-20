from nous_runtime.retrieval import registry
from nous_runtime.retrieval.backends.local import LocalRetrievalBackend
from nous_runtime.retrieval.protocol import IndexSpec


def test_local_backend_manifest_covers_reference_contract():
    backend = LocalRetrievalBackend()
    manifest = backend.manifest()

    assert manifest.name == "local"
    assert manifest.supports_lexical is True
    assert manifest.supports_filters is True
    assert manifest.multi_tenant is True
    assert manifest.supports_dense is False


def test_backend_registry_resolves_registered_backend():
    backend = registry.resolve("local")

    assert backend.manifest().name == "local"
    assert backend.health().ok is True


def test_local_backend_index_lifecycle_is_rebuildable():
    backend = LocalRetrievalBackend()
    spec = IndexSpec(name="memory")

    assert backend.verify(spec).ok is False
    assert backend.ensure_index(spec).ok is True
    assert backend.verify(spec).ok is True

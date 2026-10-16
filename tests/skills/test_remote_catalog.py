"""Controlled remote packages retain central network and existing install owners."""

import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from nous_runtime.evidence.web_gateway import WebGateway, WebRequest
from nous_runtime.skills import SkillRegistry
from tests.skills.test_skill_registry import make_skill

CATALOG = "https://catalog.example.test/catalog.json"
PACKAGE = "https://packages.example.test/code-helper.zip"


def bundle(source):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(
                    path, "code-helper/" + path.relative_to(source).as_posix()
                )
    return output.getvalue()


@pytest.fixture
def remote(tmp_path, monkeypatch):
    source = make_skill(tmp_path / "code-helper")
    local = SkillRegistry(tmp_path / "inspector")
    local.add_catalog(str(source.parent))
    entry = local.catalog_records()[0]
    raw = {
        "name": entry.skill_id,
        "description": entry.description,
        "version": entry.version,
        "digest": entry.digest,
        "source": PACKAGE,
        "requested_capabilities": list(entry.requested_capabilities),
    }
    state = {
        "catalog": {"schema": "apeir.skill-catalog/v1", "skills": [raw]},
        "package": bundle(source),
        "calls": [],
        "permissions": [],
        "revoked": False,
    }

    def transport(**kwargs):
        assert kwargs["resolved_ip"] == "8.8.8.8"
        assert kwargs["headers"]["Accept-Encoding"] == "identity"
        state["calls"].append(kwargs["url"])
        catalog = kwargs["url"] == CATALOG
        body = json.dumps(state["catalog"]).encode() if catalog else state["package"]
        return SimpleNamespace(
            status_code=200,
            headers={
                "content-type": "application/json" if catalog else "application/zip"
            },
            body=body,
        )

    # Inject only the central gateway's documented test resolver/transport seams.
    monkeypatch.setattr(
        "nous_runtime.skills.remote.WebGateway",
        lambda: WebGateway(resolver=lambda *_: ["8.8.8.8"], transport=transport),
    )

    def human():
        if state["revoked"]:
            raise PermissionError("fake human revoked")

    def permission(url):
        assert url in {CATALOG, PACKAGE}
        state["permissions"].append(url)
        if state.get("deny_url") == url:
            raise PermissionError("exact URL denied")

    registry = SkillRegistry(tmp_path / "workspace")
    registry.add_catalog(CATALOG, before_publish=human, authorize_remote=permission)
    return registry, source, state, human, permission


def install(remote, **overrides):
    registry, _, _, human, permission = remote
    entry = registry.catalog_records()[0]
    kwargs = dict(
        catalog_source=CATALOG,
        version=entry.version,
        digest=entry.digest,
        package_source=entry.source,
        before_publish=human,
        authorize_remote=permission,
    )
    kwargs.update(overrides)
    return registry.install_from_catalog(entry.skill_id, **kwargs)


def test_exact_remote_install_restart_passive_cache_and_no_execution(remote):
    registry, source, state, _, _ = remote
    state["calls"].clear()
    assert registry.catalog_records(local_only=True)
    assert registry.summaries()
    assert registry.search("helper")
    assert not state["calls"]
    first = install(remote)
    assert state["calls"] == [CATALOG, PACKAGE]
    assert PACKAGE in state["permissions"]
    assert first.digest == state["catalog"]["skills"][0]["digest"]
    assert first.metadata["authority"] == "none"
    assert (
        registry.extensions.get_record("skills/code-helper")["granted_capabilities"]
        == []
    )
    assert not (source / "executed").exists()
    restarted = SkillRegistry(registry.workspace)
    assert restarted.load("installed:code-helper").artifact_ref == first.artifact_ref
    assert restarted.catalog_records()[0].source == PACKAGE
    assert not (
        registry.extensions.package_path("skills/code-helper") / "executed"
    ).exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("before_publish", None),
        ("authorize_remote", None),
        ("package_source", "https://other.test/pkg.zip"),
        ("version", "latest"),
        ("digest", "sha256:" + "0" * 64),
    ],
)
def test_review_and_original_authority_are_mandatory(remote, field, value):
    _, _, state, _, _ = remote
    state["calls"].clear()
    with pytest.raises((PermissionError, ValueError)):
        install(remote, **{field: value})
    assert not state["calls"]


@pytest.mark.parametrize("url", [CATALOG, PACKAGE])
def test_exact_url_permission_denial_prevents_network(remote, url):
    registry, _, state, _, _ = remote
    state["calls"].clear()
    state["deny_url"] = url
    with pytest.raises(PermissionError):
        install(remote)
    assert not state["calls"] and not registry.extensions.list()


@pytest.mark.parametrize(
    "change", ["source", "digest", "capabilities", "duplicate", "package"]
)
def test_changed_remote_content_preserves_previous_valid_install(remote, change):
    registry, _, state, _, _ = remote
    first = install(remote)
    raw = state["catalog"]["skills"][0]
    if change == "source":
        raw["source"] = "https://other.test/new.zip"
    elif change == "digest":
        raw["digest"] = "sha256:" + "f" * 64
    elif change == "capabilities":
        raw["requested_capabilities"] = []
    elif change == "duplicate":
        state["catalog"]["skills"].append(dict(raw))
    else:
        with zipfile.ZipFile(io.BytesIO(state["package"])) as archive:
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w") as changed:
                for info in archive.infolist():
                    changed.writestr(
                        info.filename, archive.read(info.filename) + b"changed"
                    )
            state["package"] = output.getvalue()
    with pytest.raises(ValueError, match="changed|differs"):
        install(remote)
    assert registry.load("installed:code-helper").digest == first.digest


def test_revocation_after_acquisition_and_catalog_removal_block_publish(
    remote, monkeypatch
):
    registry, _, state, _, _ = remote
    first = install(remote)
    original = registry._remote_bytes

    def revoke(source, **kwargs):
        content = original(source, **kwargs)
        if source == PACKAGE:
            state["revoked"] = True
        return content

    monkeypatch.setattr(registry, "_remote_bytes", revoke)
    with pytest.raises(PermissionError, match="revoked"):
        install(remote)
    assert registry.load("installed:code-helper").digest == first.digest
    state["revoked"] = False

    def remove(source, **kwargs):
        content = original(source, **kwargs)
        if source == PACKAGE:
            registry.remove_catalog(CATALOG)
        return content

    monkeypatch.setattr(registry, "_remote_bytes", remove)
    with pytest.raises(PermissionError, match="removed"):
        install(remote)
    assert registry.load("installed:code-helper").digest == first.digest


def test_explicit_refresh_and_failed_refresh_preserve_original_snapshot(remote):
    registry, _, state, human, permission = remote
    state["catalog"]["skills"][0]["version"] = "2.0.0"
    assert registry.catalog_records()[0].version == "1.2.3"
    refreshed = registry.refresh_catalog(
        CATALOG, before_publish=human, authorize_remote=permission
    )
    assert refreshed[0].version == "2.0.0"
    state["catalog"]["schema"] = "unknown"
    with pytest.raises(ValueError):
        registry.refresh_catalog(
            CATALOG, before_publish=human, authorize_remote=permission
        )
    assert registry.catalog_records()[0].version == "2.0.0"


@pytest.mark.parametrize(
    "url",
    [
        "http://example.test/a",
        "https://user:fake-secret@example.test/a",
        "https://example.test/a?token=fake-secret",
        "https://example.test/a#x",
        "https://example.test/\\evil",
        "https://example.test/a\n",
        "https://example.test:0/a",
    ],
)
def test_unsafe_skill_locator_fails_before_permission_or_transport(tmp_path, url):
    registry = SkillRegistry(tmp_path)
    called = []
    with pytest.raises((PermissionError, ValueError)):
        registry.add_catalog(
            url,
            before_publish=lambda: called.append("human"),
            authorize_remote=called.append,
        )
    assert called == [] and registry.catalogs() == ()


@pytest.mark.parametrize(
    "addresses",
    [
        ["127.0.0.1"],
        ["10.0.0.1"],
        ["169.254.169.254"],
        ["::1"],
        ["8.8.8.8", "10.1.1.1"],
    ],
)
def test_binary_gateway_keeps_ssrf_checks(addresses):
    calls = []
    gateway = WebGateway(
        resolver=lambda *_: addresses, transport=lambda **kw: calls.append(kw)
    )
    result = gateway.fetch_bytes(WebRequest(url=PACKAGE))
    assert not result.response.ok and result.body == b""
    assert result.response.error_code == "NETWORK_SSRF_BLOCKED" and not calls


@pytest.mark.parametrize(
    "status,headers,body,code",
    [
        (302, {"location": "https://127.0.0.1/evil"}, b"", "NETWORK_REDIRECT_LIMIT"),
        (503, {}, b"failure", "NETWORK_HTTP_STATUS"),
        (
            200,
            {"content-encoding": "gzip"},
            b"raw",
            "NETWORK_CONTENT_ENCODING_UNSUPPORTED",
        ),
        (200, {"content-length": "9999"}, b"raw", "NETWORK_RESPONSE_TOO_LARGE"),
        (200, {"content-length": "invalid"}, b"raw", "NETWORK_INVALID_RESPONSE"),
        (200, {}, b"x" * 33, "NETWORK_RESPONSE_TOO_LARGE"),
        (
            200,
            {"content-type": "application/json"},
            b"invalid",
            "NETWORK_MIME_MISMATCH",
        ),
    ],
)
def test_binary_gateway_never_releases_rejected_response_bytes(
    status, headers, body, code
):
    gateway = WebGateway(
        resolver=lambda *_: ["8.8.8.8"],
        transport=lambda **_: SimpleNamespace(
            status_code=status, headers=headers, body=body
        ),
    )
    result = gateway.fetch_bytes(
        WebRequest(url=PACKAGE, max_redirects=0, max_size_bytes=32)
    )
    assert (
        not result.response.ok
        and result.body == b""
        and result.response.error_code == code
    )


def test_binary_gateway_preserves_non_utf8_bytes_and_text_contract():
    raw = b"PK\x03\x04\xff\x00\x80"
    gateway = WebGateway(
        resolver=lambda *_: ["8.8.8.8"],
        transport=lambda **_: SimpleNamespace(
            status_code=200, headers={"content-type": "application/zip"}, body=raw
        ),
    )
    result = gateway.fetch_bytes(WebRequest(url=PACKAGE))
    assert result.response.ok and result.body == raw
    assert result.response.content == "" and "body" not in result.response.to_dict()
    assert "\\xff" not in repr(result)
    assert gateway.fetch(WebRequest(url=PACKAGE)).content == ""


@pytest.mark.parametrize(
    "name", ["../escape", "/absolute", "C:/drive", "code-helper/../../escape"]
)
def test_remote_archive_paths_fail_closed_without_replacing_install(remote, name):
    registry, _, state, _, _ = remote
    first = install(remote)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(name, b"bad")
    state["package"] = output.getvalue()
    with pytest.raises(ValueError, match="unsafe"):
        install(remote)
    assert registry.load("installed:code-helper").digest == first.digest


@pytest.mark.parametrize("damage", ["entry", "source", "digest", "duplicate"])
def test_invalid_remote_refresh_retains_previous_valid_snapshot(remote, damage):
    registry, _, state, human, permission = remote
    if damage == "entry":
        state["catalog"]["skills"] = [None]
    elif damage == "source":
        state["catalog"]["skills"][0]["source"] = "file:///private"
    elif damage == "digest":
        state["catalog"]["skills"][0]["digest"] = "not-exact"
    else:
        state["catalog"]["skills"] *= 2
    with pytest.raises(ValueError):
        registry.refresh_catalog(
            CATALOG, before_publish=human, authorize_remote=permission
        )
    assert len(registry.catalog_records()) == 1
    assert registry.catalog_records()[0].source == PACKAGE


def test_package_url_permission_revoked_after_network_blocks_publication(
    remote, monkeypatch
):
    registry, _, state, _, _ = remote
    first = install(remote)
    original = registry._remote_bytes

    def revoke(source, **kwargs):
        content = original(source, **kwargs)
        if source == PACKAGE:
            state["deny_url"] = PACKAGE
        return content

    monkeypatch.setattr(registry, "_remote_bytes", revoke)
    with pytest.raises(PermissionError, match="denied"):
        install(remote)
    assert registry.load("installed:code-helper").digest == first.digest


@pytest.mark.parametrize("fault", ["cas", "publication"])
def test_remote_update_publication_fault_restores_old_valid_install(
    remote, monkeypatch, fault
):
    from nous_runtime.artifact import ContentAddressedArtifactStore
    from nous_runtime.extensions import ExtensionInspector

    registry, source, state, human, permission = remote
    first = install(remote)
    (source / "SKILL.md").write_text(
        (source / "SKILL.md").read_text().replace("1.2.3", "1.2.4")
    )
    manifest = ExtensionInspector().inspect(source)
    state["catalog"]["skills"][0].update(
        version=manifest.version, digest=manifest.provenance.digest
    )
    state["package"] = bundle(source)
    registry.refresh_catalog(CATALOG, before_publish=human, authorize_remote=permission)
    original_files = {
        path: path.read_bytes()
        for path in (registry.extensions.index_path, registry.extensions.lock_path)
    }

    def fail(*_args, **_kwargs):
        raise OSError("fake publication fault")

    if fault == "cas":
        monkeypatch.setattr(ContentAddressedArtifactStore, "store_bytes", fail)
    else:
        monkeypatch.setattr(registry.extensions, "_write_lock", fail)
    with pytest.raises(OSError, match="publication fault"):
        install(remote)
    assert all(path.read_bytes() == content for path, content in original_files.items())
    assert registry.load("installed:code-helper").digest == first.digest
    assert registry.load("installed:code-helper").version == "1.2.3"


@pytest.mark.parametrize(
    "source", ["\x00https://example.test/catalog.json", "https://example.test/a\x7f"]
)
def test_hidden_url_controls_cannot_change_original_permission_locator(
    tmp_path, source
):
    called = []
    with pytest.raises(ValueError):
        SkillRegistry(tmp_path).add_catalog(
            source,
            before_publish=lambda: called.append("human"),
            authorize_remote=called.append,
        )
    assert called == []


def test_dns_rebinding_after_initial_check_prevents_binary_transport():
    addresses = iter([["8.8.8.8"], ["127.0.0.1"]])
    called = []
    gateway = WebGateway(
        resolver=lambda *_: next(addresses), transport=lambda **kw: called.append(kw)
    )
    result = gateway.fetch_bytes(WebRequest(url=PACKAGE))
    assert result.response.error_code == "NETWORK_SSRF_BLOCKED"
    assert result.body == b"" and not called


def test_non_zip_remote_bytes_preserve_previous_install(remote):
    registry, _, state, _, _ = remote
    first = install(remote)
    state["package"] = b"not-a-zip\xff"
    with pytest.raises(ValueError, match="valid ZIP"):
        install(remote)
    assert registry.load("installed:code-helper").digest == first.digest


def test_extension_revocation_during_cas_cannot_be_overwritten_by_remote_install(
    remote, monkeypatch
):
    from nous_runtime.artifact import ContentAddressedArtifactStore

    registry, _, _, _, _ = remote
    install(remote)
    original = ContentAddressedArtifactStore.store_bytes

    def revoke(store, *args, **kwargs):
        result = original(store, *args, **kwargs)
        index = json.loads(registry.extensions.index_path.read_text())
        index["extensions"]["skills/code-helper"]["state"] = "revoked"
        registry.extensions.index_path.write_text(json.dumps(index))
        return result

    monkeypatch.setattr(ContentAddressedArtifactStore, "store_bytes", revoke)
    with pytest.raises(PermissionError, match="revoked"):
        install(remote)
    assert registry.extensions.get_record("skills/code-helper")["state"] == "revoked"
    with pytest.raises(KeyError):
        registry.load("installed:code-helper")

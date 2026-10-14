"""Canonical Extension index writers serialize without deadlocking host callbacks."""

from contextlib import contextmanager
import threading
import time

import pytest

from nous_runtime.extensions.registry import ExtensionRegistry
from tests.skills.test_skill_registry import make_skill


def decision(manifest, *, grants=()):
    return dict(
        normalized_digest=manifest.provenance.digest,
        approval_required=False,
        receipt_id="fake-bound-receipt",
        policy_version="fake-test-policy",
        granted_capabilities=list(grants),
    )


def setup(tmp_path):
    root = tmp_path / "registry"
    installer = ExtensionRegistry(root)
    actor = ExtensionRegistry(root)
    source = make_skill(tmp_path / "source" / "code-helper")
    first = installer.install(source)
    sibling = installer.install(make_skill(tmp_path / "source" / "other", name="other"))
    installer.record_admission(
        first.extension_id, decision(first, grants=["filesystem.read"])
    )
    return installer, actor, source, first, sibling


@pytest.mark.parametrize("mutation", ["revoke", "admit_sibling"])
def test_competing_writer_cannot_be_lost_during_install(
    tmp_path, monkeypatch, mutation
):
    import nous_runtime.extensions.registry as owner

    installer, actor, source, first, sibling = setup(tmp_path)
    held = threading.Event()
    release = threading.Event()
    attempted = threading.Event()
    completed = threading.Event()
    errors = []
    original_lock = owner.file_lock

    @contextmanager
    def observed_lock(path):
        if threading.current_thread().name == "competing-extension-writer":
            attempted.set()
        with original_lock(path):
            yield

    monkeypatch.setattr(owner, "file_lock", observed_lock)

    def before_publish():
        held.set()
        if not release.wait(5):
            raise RuntimeError("test failed to release original install")

    def install():
        try:
            installer.install(source, before_publish=before_publish)
        except Exception as exc:
            errors.append(exc)

    def mutate():
        try:
            if mutation == "revoke":
                actor.record_revocation(first.extension_id, decision(first))
            else:
                actor.record_admission(
                    sibling.extension_id, decision(sibling, grants=["filesystem.read"])
                )
        except Exception as exc:
            errors.append(exc)
        finally:
            completed.set()

    install_thread = threading.Thread(target=install, daemon=True)
    mutate_thread = threading.Thread(
        target=mutate, name="competing-extension-writer", daemon=True
    )
    install_thread.start()
    try:
        assert held.wait(5)
        mutate_thread.start()
        deadline = time.monotonic() + 5
        # Before repair, mutation finishes outside the install lock. After
        # repair it reaches that same lock and waits for the original install.
        while (
            not attempted.is_set()
            and not completed.is_set()
            and time.monotonic() < deadline
        ):
            completed.wait(0.01)
        assert attempted.is_set() or completed.is_set()
    finally:
        release.set()
        install_thread.join(5)
        if mutate_thread.ident is not None:
            mutate_thread.join(5)
    assert not install_thread.is_alive() and not mutate_thread.is_alive()
    assert not errors
    current = ExtensionRegistry(installer.root)
    if mutation == "revoke":
        record = current.get_record(first.extension_id)
        assert record["state"] == "revoked" and record["authority"] == "none"
        assert record["granted_capabilities"] == []
    else:
        assert current.get_record(sibling.extension_id)["granted_capabilities"] == [
            "filesystem.read"
        ]
    assert (
        current.verify(first.extension_id).provenance.digest == first.provenance.digest
    )
    assert (
        current.verify(sibling.extension_id).provenance.digest
        == sibling.provenance.digest
    )
    assert len(current.list()) == 2
    assert current.get_record(first.extension_id)["previous_granted_capabilities"] == [
        "filesystem.read"
    ]


def test_same_thread_callback_revocation_through_other_instance_is_terminal(tmp_path):
    installer, actor, source, first, sibling = setup(tmp_path)
    with pytest.raises(PermissionError, match="revoked"):
        installer.install(
            source,
            before_publish=lambda: actor.record_revocation(
                first.extension_id, decision(first)
            ),
        )
    assert actor.get_record(first.extension_id)["state"] == "revoked"
    assert (
        installer.verify(first.extension_id).provenance.digest
        == first.provenance.digest
    )
    assert (
        installer.verify(sibling.extension_id).provenance.digest
        == sibling.provenance.digest
    )


def test_same_thread_callback_admission_preserves_other_record(tmp_path):
    installer, actor, source, first, sibling = setup(tmp_path)
    installer.install(
        source,
        before_publish=lambda: actor.record_admission(
            sibling.extension_id, decision(sibling, grants=["filesystem.read"])
        ),
    )
    assert installer.get_record(sibling.extension_id)["granted_capabilities"] == [
        "filesystem.read"
    ]
    assert (
        installer.verify(first.extension_id).provenance.digest
        == first.provenance.digest
    )
    assert (
        installer.verify(sibling.extension_id).provenance.digest
        == sibling.provenance.digest
    )


def test_stale_admission_cannot_restore_canonical_revocation(tmp_path):
    installer, actor, _, first, _ = setup(tmp_path)
    actor.record_revocation(first.extension_id, decision(first))
    with pytest.raises(PermissionError, match="revoked"):
        installer.record_admission(
            first.extension_id, decision(first, grants=["filesystem.read"])
        )
    assert actor.get_record(first.extension_id)["state"] == "revoked"
    assert actor.get_record(first.extension_id)["granted_capabilities"] == []


@pytest.mark.parametrize(
    "mutation",
    [
        "permission_request",
        "clear_permission",
        "permission_approval",
        "discovery",
        "remove",
        "sign",
    ],
)
def test_unrelated_canonical_index_writers_survive_install_callback(tmp_path, mutation):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    installer, actor, source, first, sibling = setup(tmp_path)
    if mutation in {"clear_permission", "permission_approval"}:
        actor.record_permission_request(
            sibling.extension_id,
            request_id="fake-request",
            proposal_hash="fake-proposal",
            capabilities=("filesystem.read",),
        )
    key_path = tmp_path / "fake-signing.key"
    if mutation == "sign":
        key_path.write_bytes(
            Ed25519PrivateKey.generate().private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        key_path.chmod(0o600)

    def update():
        if mutation == "permission_request":
            actor.record_permission_request(
                sibling.extension_id,
                request_id="fake-request",
                proposal_hash="fake-proposal",
                capabilities=("filesystem.read",),
            )
        elif mutation == "clear_permission":
            actor.clear_permission_request(sibling.extension_id)
        elif mutation == "permission_approval":
            actor.record_permission_approval(
                sibling.extension_id,
                request_id="fake-request",
                proposal_hash="fake-proposal",
                approval_id="fake-approval",
            )
        elif mutation == "discovery":
            actor.record_discovered_tools(
                sibling.extension_id,
                [{"name": "fake-bounded-tool"}],
                discovery_receipt_id="fake-discovery",
            )
        elif mutation == "remove":
            assert actor.remove(sibling.extension_id)
        else:
            actor.sign(sibling.extension_id, key_path)

    installer.install(source, before_publish=update)
    current = installer.get_record(sibling.extension_id)
    if mutation == "permission_request":
        assert current["state"] == "approval_pending"
        assert current["pending_permission_request"]["request_id"] == "fake-request"
    elif mutation == "clear_permission":
        assert "pending_permission_request" not in current
    elif mutation == "permission_approval":
        assert current["pending_permission_request"]["approval_id"] == "fake-approval"
    elif mutation == "discovery":
        assert actor.read_discovered_tools(sibling.extension_id) == [
            {"name": "fake-bounded-tool"}
        ]
    elif mutation == "remove":
        assert current is None and len(installer.list()) == 1
    else:
        assert (
            current["signature_status"] == "Verified" and current["authority"] == "none"
        )
    assert (
        installer.verify(first.extension_id).provenance.digest
        == first.provenance.digest
    )
    if mutation != "remove":
        assert (
            installer.verify(sibling.extension_id).provenance.digest
            == sibling.provenance.digest
        )


@pytest.mark.parametrize("mutation", ["install", "permission_request", "sign"])
def test_other_metadata_paths_cannot_restore_revoked_extension(tmp_path, mutation):
    installer, actor, source, first, _ = setup(tmp_path)
    actor.record_revocation(first.extension_id, decision(first))
    with pytest.raises(PermissionError, match="revoked"):
        if mutation == "install":
            installer.install(source)
        elif mutation == "permission_request":
            installer.record_permission_request(
                first.extension_id,
                request_id="fake-request",
                proposal_hash="fake-proposal",
                capabilities=("filesystem.read",),
            )
        else:
            installer.sign(first.extension_id, tmp_path / "unneeded-key")
    assert actor.get_record(first.extension_id)["state"] == "revoked"
    assert actor.get_record(first.extension_id)["authority"] == "none"


def test_removal_cannot_erase_persisted_revocation(tmp_path):
    installer, actor, source, first, _ = setup(tmp_path)
    actor.record_revocation(first.extension_id, decision(first))
    with pytest.raises(PermissionError, match="revoked"):
        installer.remove(first.extension_id)
    restored = ExtensionRegistry(installer.root)
    assert restored.get_record(first.extension_id)["state"] == "revoked"
    with pytest.raises(PermissionError, match="revoked"):
        restored.install(source)


@pytest.mark.parametrize("binding", ["digest", "version", "skill_id"])
def test_bound_remove_validates_current_canonical_content(tmp_path, binding):
    installer, _, _, first, _ = setup(tmp_path)
    kwargs = {"expected_" + binding: "wrong-original-binding"}
    with pytest.raises(PermissionError, match="review"):
        installer.remove(first.extension_id, **kwargs)
    assert (
        installer.verify(first.extension_id).provenance.digest
        == first.provenance.digest
    )


def test_bound_remove_reloads_revocation_after_trusted_callback(tmp_path):
    installer, actor, _, first, _ = setup(tmp_path)

    def revoke():
        actor.record_revocation(first.extension_id, decision(first))

    with pytest.raises(PermissionError, match="revoked"):
        installer.remove(
            first.extension_id,
            expected_digest=first.provenance.digest,
            expected_version=first.version,
            expected_skill_id=first.skills[0].name,
            before_remove=revoke,
        )
    assert actor.get_record(first.extension_id)["state"] == "revoked"

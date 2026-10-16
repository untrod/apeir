"""Skill UI actions use the existing human authority and canonical registry."""

import json
from contextlib import contextmanager

import pytest

from nous_runtime.api.routes import route_server
from nous_runtime.artifact import ContentAddressedArtifactStore
from nous_runtime.governance.permission import PermissionRule
from nous_runtime.skills import SkillRegistry
from nous_runtime.skills import registry as registry_module
from tests.control_plane.test_operations import (
    plane as plane_fixture,
    human_env as human_env_fixture,
)
from tests.control_plane.test_human_sessions import login
from tests.skills.test_skill_registry import make_skill

plane = plane_fixture
human_env = human_env_fixture


@pytest.fixture
def skill_plane(plane, tmp_path):
    view, auth, client = plane
    source = make_skill(tmp_path / "catalog" / "code-helper")
    registry = SkillRegistry(view.root)
    registry.add_catalog(str(source.parent))
    for action in (
        "governance.approve",
        "control.skill_install",
        "control.skill_manage",
        "control.skill_load",
    ):
        auth.permissions.add(
            PermissionRule("oidc:*:alice", action, "skill:code-helper")
        )
    issued, context = login(auth, client)
    entry = next(row for row in view.skills()[0] if row["provider"] == "catalog")
    return view, auth, context, entry, issued


def body(row, action):
    return {
        "kind": "skills",
        "action": action,
        "target_id": row["skill_key"],
        "version": row["version"],
        "digest": row["digest"],
    }


def test_review_install_load_disable_restart_and_uninstall(skill_plane):
    view, _, context, entry, _ = skill_plane
    result = view.action(body(entry, "install"), context)
    assert result["authority"] == "none" and not result["execution_performed"]
    installed = next(
        row for row in view.snapshot()["skills"] if row["provider"] == "installed"
    )
    loaded = view.action(body(installed, "load"), context)
    assert loaded["skill"]["skill"]["instructions"]
    assert not view.gate.store.list_active_leases()
    view.action(body(installed, "disable"), context)
    with pytest.raises(PermissionError):
        view.action(body(installed, "load"), context)
    assert (
        not SkillRegistry(view.root)
        .resolve("installed:code-helper", include_disabled=True)
        .enabled
    )
    view.action(body(installed, "enable"), context)
    assert view.action(body(installed, "remove"), context)["skill"]["removed"]
    assert not SkillRegistry(view.root).extensions.list()
    rows = [
        json.loads(item["evidence_json"])
        for item in view.gate.store.operation_audit()
        if item["event_type"] == "skill.management.completed"
    ]
    assert {row["action"] for row in rows} == {
        "install",
        "load",
        "disable",
        "enable",
        "remove",
    }
    assert all(
        row["human_session_id"] == context.session_id
        and not row["execution_authority_issued"]
        for row in rows
    )


def test_model_service_cannot_install_and_human_nonce_cannot_replay(
    skill_plane, monkeypatch
):
    view, auth, context, entry, issued = skill_plane
    path = "/api/v1/control/operations/actions"
    request = body(entry, "install")
    monkeypatch.setenv("NOUS_API_TOKEN", "skill-center.fake.service-token")
    assert not route_server(
        "POST",
        path,
        body=request,
        auth={"token": "skill-center.fake.service-token", "loopback": True},
    )["ok"]
    nonce = auth.nonce(context, "POST", path, request)["nonce"]
    headers = {
        "cookie": "apeir_human=" + issued.session_cookie,
        "x-control-nonce": nonce,
    }
    assert route_server("POST", path, body=request, auth={"headers": headers})["ok"]
    assert not route_server("POST", path, body=request, auth={"headers": headers})["ok"]


def test_expiry_during_content_acquisition_prevents_publication(
    skill_plane, monkeypatch
):
    view, _, context, entry, _ = skill_plane
    original = ContentAddressedArtifactStore.store_bytes

    def expire(store, *args, **kwargs):
        result = original(store, *args, **kwargs)
        with view.gate.store.operation_transaction() as db:
            db.execute("UPDATE governance_human_sessions SET expires_at=0")
        return result

    monkeypatch.setattr(ContentAddressedArtifactStore, "store_bytes", expire)
    with pytest.raises(PermissionError):
        view.action(body(entry, "install"), context)
    assert not SkillRegistry(view.root).extensions.list()


def test_changed_review_and_unregistered_source_are_rejected(skill_plane):
    view, _, context, entry, _ = skill_plane
    request = body(entry, "install") | {"digest": "sha256:" + "0" * 64}
    with pytest.raises(PermissionError, match="changed"):
        view.action(request, context)
    with pytest.raises(KeyError):
        view.action(
            body(entry, "install") | {"target_id": "catalog:arbitrary-url"}, context
        )
    assert not SkillRegistry(view.root).extensions.list()


def test_passive_snapshot_never_fetches_remote_catalog(plane, monkeypatch):
    view, _, _ = plane
    registry = SkillRegistry(view.root)
    registry._write_state(
        {
            "schema": "apeir.skill-registry-state/v1",
            "enabled": {},
            "catalogs": ["https://example.test/catalog.json"],
        }
    )

    def fail(*args):
        raise AssertionError("snapshot attempted network fetch")

    from nous_runtime.evidence.web_gateway import WebGateway

    monkeypatch.setattr(WebGateway, "fetch", fail)
    snapshot = view.snapshot()
    assert snapshot["skill_diagnostics"] and "instructions" not in json.dumps(
        snapshot["skills"]
    )


def _revoke_skill_human(view, auth, fault, action):
    if fault == "permission":
        auth.permissions.add(
            PermissionRule(
                "oidc:*:alice", "control." + action, "skill:code-helper", effect="deny"
            )
        )
    else:
        with view.gate.store.operation_transaction() as db:
            db.execute("UPDATE governance_human_sessions SET status='REVOKED'")


@pytest.mark.parametrize("action", ["enable", "disable"])
@pytest.mark.parametrize("fault", ["permission", "session"])
def test_current_authority_rechecked_inside_skill_enabled_publication_fence(
    skill_plane, monkeypatch, action, fault
):
    view, auth, context, entry, _ = skill_plane
    view.action(body(entry, "install"), context)
    registry = SkillRegistry(view.root)
    if action == "enable":
        registry.disable("installed:code-helper")
    installed = next(row for row in view.skills()[0] if row["provider"] == "installed")
    previous = registry.state_path.read_bytes()
    original_lock = registry_module.file_lock
    intervened = False

    @contextmanager
    def intervening_lock(path):
        nonlocal intervened
        with original_lock(path):
            if path == registry.state_path.with_suffix(".lock") and not intervened:
                intervened = True
                _revoke_skill_human(view, auth, fault, "skill_manage")
            yield

    monkeypatch.setattr(registry_module, "file_lock", intervening_lock)
    with pytest.raises(PermissionError):
        view.action(body(installed, action), context)
    assert intervened
    assert registry.state_path.read_bytes() == previous
    current = SkillRegistry(view.root).resolve(
        "installed:code-helper", include_disabled=True
    )
    assert current.enabled == installed["enabled"]
    assert current.digest == installed["digest"]
    assert not view.gate.store.list_active_leases()


@pytest.mark.parametrize("fault", ["permission", "session"])
def test_current_authority_rechecked_after_skill_instruction_acquisition(
    skill_plane, monkeypatch, fault
):
    view, auth, context, entry, _ = skill_plane
    view.action(body(entry, "install"), context)
    installed = next(row for row in view.skills()[0] if row["provider"] == "installed")
    original_load = SkillRegistry.load

    def intervening_load(registry, *args, **kwargs):
        _revoke_skill_human(view, auth, fault, "skill_load")
        return original_load(registry, *args, **kwargs)

    monkeypatch.setattr(SkillRegistry, "load", intervening_load)
    with pytest.raises(PermissionError):
        view.action(body(installed, "load"), context)
    assert not view.gate.store.list_active_leases()


@pytest.mark.parametrize("action", ["enable", "disable"])
@pytest.mark.parametrize("fault", ["version", "digest", "corrupt"])
def test_stale_skill_review_cannot_toggle_changed_or_corrupt_installed_content(
    skill_plane, monkeypatch, tmp_path, action, fault
):
    view, _, context, entry, _ = skill_plane
    view.action(body(entry, "install"), context)
    registry = SkillRegistry(view.root)
    if action == "enable":
        registry.disable("installed:code-helper")
    installed = next(row for row in view.skills()[0] if row["provider"] == "installed")
    previous = registry.state_path.read_bytes()
    source = make_skill(
        tmp_path / "new-reviewed-content" / "code-helper",
        version="1.2.4" if fault == "version" else installed["version"],
    )
    if fault == "digest":
        with (source / "SKILL.md").open("a", encoding="utf-8") as stream:
            stream.write("\nChanged reviewed instructions.\n")
    original_lock = registry_module.file_lock
    intervened = False

    @contextmanager
    def intervening_lock(path):
        nonlocal intervened
        with original_lock(path):
            if path == registry.state_path.with_suffix(".lock") and not intervened:
                intervened = True
                if fault == "corrupt":
                    package = registry.extensions.package_path(
                        installed["extension_id"]
                    )
                    with (package / "SKILL.md").open("a", encoding="utf-8") as stream:
                        stream.write("\nUnpublished corrupt content.\n")
                else:
                    registry.install(source)
            yield

    monkeypatch.setattr(registry_module, "file_lock", intervening_lock)
    with pytest.raises((PermissionError, KeyError)):
        view.action(body(installed, action), context)
    assert intervened
    assert registry.state_path.read_bytes() == previous
    if fault != "corrupt":
        current = SkillRegistry(view.root).resolve(
            "installed:code-helper", include_disabled=True
        )
        assert current.digest != installed["digest"]
        assert current.enabled == installed["enabled"]
    assert not view.gate.store.list_active_leases()


@pytest.mark.parametrize(
    "fault", ["version", "digest", "disabled", "corrupt", "revoked"]
)
def test_instruction_delivery_refuses_content_invalidated_during_read(
    skill_plane, monkeypatch, tmp_path, fault
):
    view, _, context, entry, _ = skill_plane
    view.action(body(entry, "install"), context)
    registry = SkillRegistry(view.root)
    installed = next(row for row in view.skills()[0] if row["provider"] == "installed")
    source = make_skill(
        tmp_path / "changed-instructions" / "code-helper",
        version="1.2.4" if fault == "version" else installed["version"],
    )
    if fault == "digest":
        with (source / "SKILL.md").open("a", encoding="utf-8") as stream:
            stream.write("\nChanged instructions.\n")
    original_load = SkillRegistry.load
    intervened = False

    def intervening_load(owner, *args, **kwargs):
        nonlocal intervened
        acquired = original_load(owner, *args, **kwargs)
        if not intervened:
            intervened = True
            if fault in {"version", "digest"}:
                registry.install(source)
            elif fault == "disabled":
                registry.disable("installed:code-helper")
            elif fault == "corrupt":
                package = registry.extensions.package_path(installed["extension_id"])
                with (package / "SKILL.md").open("a", encoding="utf-8") as stream:
                    stream.write("\nUnpublished corrupt content.\n")
            else:
                manifest = registry.extensions.verify(installed["extension_id"])
                registry.extensions.record_revocation(
                    installed["extension_id"],
                    {
                        "normalized_digest": manifest.provenance.digest,
                        "granted_capabilities": [],
                    },
                )
        return acquired

    monkeypatch.setattr(SkillRegistry, "load", intervening_load)
    with pytest.raises((PermissionError, KeyError)):
        view.action(body(installed, "load"), context)
    assert intervened
    assert not view.gate.store.list_active_leases()

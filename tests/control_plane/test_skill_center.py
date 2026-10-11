"""Skill UI actions use the existing human authority and canonical registry."""

import json

import pytest

from nous_runtime.api.routes import route_server
from nous_runtime.artifact import ContentAddressedArtifactStore
from nous_runtime.governance.permission import PermissionRule
from nous_runtime.skills import SkillRegistry
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

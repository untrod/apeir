"""Owned HTTP control actions acquire packages through an actual owned TLS server."""

import http.client
import io
import json
import os
from collections import deque
from functools import wraps
from pathlib import Path
import socket
import threading
import time
import zipfile

import pytest

from nous_runtime.api.server import RuntimeAPIHandler, RuntimeHTTPServer
from nous_runtime.artifact import ContentAddressedArtifactStore
from nous_runtime.control_plane import human_sessions, operations
from nous_runtime.control_plane.human_sessions import HumanSessionAuth
from nous_runtime.control_plane.operations import OperationsPlane
from nous_runtime.governance import ExecutionAuthorizationGate, GovernanceStore
from nous_runtime.extensions.registry import ExtensionRegistry
from nous_runtime.governance.permission import PermissionEngine, PermissionRule
from nous_runtime.skills import SkillRegistry
from tests.control_plane.test_human_sessions import login
from tests.control_plane.test_operations import (
    plane as plane_fixture,
    human_env as human_env_fixture,
)
from tests.skills.test_remote_catalog_tls import tls_catalog as tls_catalog_fixture

plane = plane_fixture
human_env = human_env_fixture
tls_catalog = tls_catalog_fixture
ACTION_PATH = "/api/v1/control/operations/actions"


class _HTTPPhases:
    """Bounded fixture-only timings; never retain arguments, paths or results."""

    def __init__(self):
        self.completed = deque(maxlen=128)
        self.active = {}
        self.lock = threading.Lock()
        self.sequence = 0
        self.local = threading.local()

    def watch(self, monkeypatch, owner, name, phase):
        original = getattr(owner, name)

        @wraps(original)
        def observed(*args, **kwargs):
            started = time.monotonic()
            with self.lock:
                self.sequence += 1
                sequence = self.sequence
                request = getattr(self.local, "request", sequence)
                if phase == "http":
                    self.local.request = request = sequence
                self.active[sequence] = (phase, request, started)
            try:
                return original(*args, **kwargs)
            finally:
                with self.lock:
                    self.active.pop(sequence)
                    self.completed.append(
                        {
                            "phase": phase,
                            "request": request,
                            "elapsed_ms": (time.monotonic() - started) * 1000,
                            "complete": True,
                        }
                    )
                if phase == "http":
                    del self.local.request

        monkeypatch.setattr(owner, name, observed)

    def snapshot(self):
        with self.lock:
            now = time.monotonic()
            return list(self.completed) + [
                {
                    "phase": phase,
                    "request": request,
                    "elapsed_ms": (now - started) * 1000,
                    "complete": False,
                }
                for phase, request, started in self.active.values()
            ]


def test_phase_diagnostic_preserves_results_errors_and_excludes_payloads(monkeypatch):
    private = "FAKE_ONLY_DIAGNOSTIC_PRIVATE_VALUE"
    phases = _HTTPPhases()
    calls = []

    class Subject:
        def run(self, value, *, fail=False):
            calls.append(value)
            assert any(not item["complete"] for item in phases.snapshot())
            if fail:
                raise ValueError(value)
            return value

    phases.watch(monkeypatch, Subject, "run", "cas_receipt")
    subject = Subject()
    assert subject.run(private) == private
    with pytest.raises(ValueError, match=private):
        subject.run(private, fail=True)
    assert calls == [private, private]
    records = phases.snapshot()
    assert len(records) == 2 and all(item["complete"] for item in records)
    assert all(item["elapsed_ms"] >= 0 for item in records)
    assert private not in json.dumps(records)
    for _ in range(140):
        assert subject.run(private) == private
    assert len(phases.snapshot()) == 128 and not phases.active


@pytest.fixture
def remote_http(plane, tls_catalog, monkeypatch):
    from nous_runtime.evidence import web_gateway
    from nous_runtime.artifact import content_store

    phases = _HTTPPhases()
    for owner, name, phase in (
        (RuntimeAPIHandler, "_dispatch", "http"),
        (OperationsPlane, "_admit", "governance_admission"),
        (SkillRegistry, "install_from_catalog", "catalog_install"),
        (SkillRegistry, "install", "skill_install"),
        (ExtensionRegistry, "_install", "extension_publish"),
        (ContentAddressedArtifactStore, "_commit", "cas_commit"),
        (ContentAddressedArtifactStore, "_receipt", "cas_receipt"),
        (content_store, "_atomic_write_bytes", "cas_durable_write"),
    ):
        phases.watch(monkeypatch, owner, name, phase)

    # Each owned server is a separate test environment. Keep the real limiter
    # and its default budget, with a fresh window rather than prior test traffic.
    monkeypatch.setattr(
        web_gateway, "_EGRESS_RATE_LIMITER", web_gateway._EgressRateLimiter()
    )
    view, auth, client = plane
    root, catalog_url, package_url, entry, connections = tls_catalog
    for resource in ("skill:code-helper", "skill-catalog:" + catalog_url):
        for action in (
            "governance.approve",
            "control.skill_manage",
            "control.skill_install",
            "control.skill_load",
        ):
            auth.permissions.add(PermissionRule("oidc:*:alice", action, resource))
    for source in (catalog_url, package_url):
        auth.permissions.add(PermissionRule("oidc:*:alice", "tool.web_fetch", source))
    issued, context = login(auth, client)
    server = RuntimeHTTPServer(("127.0.0.1", 0), RuntimeAPIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(path, body=None, *, nonce="", cookie=True, token=""):
        # Connect only this owned HTTP endpoint directly, leaving the TLS
        # fixture's public-address routing and certificate checks unchanged.
        connection = http.client.HTTPConnection(
            "127.0.0.1", server.server_port, timeout=5
        )
        connection.sock = socket.socket()
        connection.sock.settimeout(5)
        connection.sock.connect(("127.0.0.1", server.server_port))
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = "apeir_human=" + issued.session_cookie
        if nonce:
            headers["X-Control-Nonce"] = nonce
        if token:
            headers["Authorization"] = "Bearer " + token
        try:
            connection.request(
                "POST" if body is not None else "GET",
                path,
                json.dumps(body) if body is not None else None,
                headers,
            )
            response = connection.getresponse()
            result = json.loads(response.read())
            assert response.headers["Cache-Control"] == "no-store"
            return result
        except TimeoutError:
            # Preserve the original five-second deadline. A client traceback
            # alone cannot distinguish Runtime auth/store work from transport
            # delay; capture only thread code locations, never frame locals.
            import faulthandler

            faulthandler.dump_traceback()
            print("SKILL_HTTP_PHASES=" + json.dumps(phases.snapshot()), flush=True)
            raise
        finally:
            connection.close()

    def mutate(body):
        proof = request(
            "/api/v1/control/human/nonce",
            {"method": "POST", "path": ACTION_PATH, "body": body},
        )
        assert proof["ok"], proof
        return request(ACTION_PATH, body, nonce=proof["data"]["nonce"])

    yield (
        view,
        auth,
        context,
        root,
        catalog_url,
        package_url,
        entry,
        connections,
        request,
        mutate,
    )
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    if os.environ.get("APEIR_SKILL_HTTP_DIAGNOSTIC") == "1":
        print("SKILL_HTTP_PHASES=" + json.dumps(phases.snapshot()), flush=True)


def catalog_body(source, action="catalog_add"):
    return dict(kind="skills", action=action, target_id=source, catalog_source=source)


def install_body(row):
    return dict(
        kind="skills",
        action="install",
        target_id=row["skill_key"],
        catalog_source=row["catalog_source"],
        package_source=row["package_source"],
        version=row["version"],
        digest=row["digest"],
    )


def prepare(remote_http):
    view, _, _, _, catalog_url, _, _, _, request, mutate = remote_http
    response = mutate(catalog_body(catalog_url))
    assert response["ok"], response
    snapshot = request("/api/v1/control/operations")["data"]
    row = next(row for row in snapshot["skills"] if row["provider"] == "catalog")
    assert row["package_source"] == remote_http[5]
    return install_body(row)


def test_http_tls_catalog_review_install_passive_reads_and_remove(remote_http):
    view, _, context, _, catalog_url, _, entry, connections, request, mutate = (
        remote_http
    )
    body = prepare(remote_http)
    count = len(connections)
    for _ in range(2):
        snapshot = request("/api/v1/control/operations")["data"]
        assert snapshot["skill_catalogs"] == [{"source": catalog_url, "remote": True}]
        assert "instructions" not in json.dumps(snapshot["skills"])
    assert len(connections) == count
    assert mutate(catalog_body(catalog_url, "catalog_refresh"))["ok"]
    response = mutate(body)
    assert response["ok"], response
    assert response["data"]["authority"] == "none"
    assert not response["data"]["execution_performed"]
    assert SkillRegistry(view.root).load("installed:code-helper").digest == entry.digest
    assert not view.gate.store.list_active_leases()
    assert mutate(catalog_body(catalog_url, "catalog_remove"))["ok"]
    assert request("/api/v1/control/operations")["data"]["skill_catalogs"] == []
    # Removing discovery metadata does not uninstall the verified package.
    assert SkillRegistry(view.root).load("installed:code-helper").digest == entry.digest
    audits = [
        json.loads(row["evidence_json"])
        for row in view.gate.store.operation_audit()
        if row["event_type"] == "skill.catalog.management.completed"
    ]
    assert len(audits) == 3
    assert all(
        row["human_session_id"] == context.session_id
        and not row["execution_authority_issued"]
        for row in audits
    )


@pytest.mark.parametrize("denied", ["catalog", "package"])
def test_http_exact_network_denial_prevents_any_install_fetch(remote_http, denied):
    view, auth, _, _, catalog_url, package_url, _, connections, _, mutate = remote_http
    body = prepare(remote_http)
    auth.permissions.add(
        PermissionRule(
            "oidc:*:alice",
            "tool.web_fetch",
            catalog_url if denied == "catalog" else package_url,
            effect="deny",
        )
    )
    count = len(connections)
    assert not mutate(body)["ok"]
    assert len(connections) == count
    assert not SkillRegistry(view.root).extensions.list()


def test_http_catalog_control_permission_does_not_supply_network_permission(
    remote_http,
):
    view, auth, _, _, catalog_url, _, _, connections, _, mutate = remote_http
    auth.permissions = PermissionEngine(
        (
            PermissionRule(
                "oidc:*:alice", "governance.approve", "skill-catalog:" + catalog_url
            ),
            PermissionRule(
                "oidc:*:alice", "control.skill_manage", "skill-catalog:" + catalog_url
            ),
        )
    )
    count = len(connections)
    assert not mutate(catalog_body(catalog_url))["ok"]
    assert len(connections) == count
    assert not SkillRegistry(view.root).catalogs()


@pytest.mark.parametrize(
    "field", ["catalog_source", "package_source", "version", "digest"]
)
def test_http_original_nonce_binds_every_reviewed_remote_locator(remote_http, field):
    view, _, _, _, _, _, _, connections, request, mutate = remote_http
    body = prepare(remote_http)
    proof = request(
        "/api/v1/control/human/nonce",
        {"method": "POST", "path": ACTION_PATH, "body": body},
    )["data"]["nonce"]
    changed = body | {field: str(body[field]) + "changed"}
    count = len(connections)
    assert not request(ACTION_PATH, changed, nonce=proof)["ok"]
    assert len(connections) == count
    assert not SkillRegistry(view.root).extensions.list()
    assert mutate(body)["ok"]


def test_http_replay_and_service_claim_cannot_acquire_packages(
    remote_http, monkeypatch
):
    _, _, _, _, _, _, _, connections, request, _ = remote_http
    body = prepare(remote_http)
    proof = request(
        "/api/v1/control/human/nonce",
        {"method": "POST", "path": ACTION_PATH, "body": body},
    )["data"]["nonce"]
    monkeypatch.setenv("NOUS_API_TOKEN", "remote-skill.fake.service-token")
    count = len(connections)
    assert not request(
        ACTION_PATH, body, cookie=False, token="remote-skill.fake.service-token"
    )["ok"]
    assert len(connections) == count
    assert request(ACTION_PATH, body, nonce=proof)["ok"]
    count = len(connections)
    assert not request(ACTION_PATH, body, nonce=proof)["ok"]
    assert len(connections) == count


@pytest.mark.parametrize(
    "fault",
    [
        "human",
        "catalog_permission",
        "package_permission",
        "skill_permission",
        "catalog_remove",
        "catalog_changed",
        "package_changed",
    ],
)
def test_http_revalidation_after_actual_tls_acquisition_blocks_publication(
    remote_http, monkeypatch, fault
):
    view, auth, _, _, catalog_url, package_url, _, _, _, mutate = remote_http
    body = prepare(remote_http)
    original = SkillRegistry._remote_bytes

    def interrupt(source, **kwargs):
        content = original(source, **kwargs)
        if source == package_url:
            if fault == "human":
                with view.gate.store.operation_transaction() as db:
                    db.execute("UPDATE governance_human_sessions SET status='REVOKED'")
            elif fault == "skill_permission":
                auth.permissions.add(
                    PermissionRule(
                        "oidc:*:alice",
                        "control.skill_install",
                        "skill:code-helper",
                        effect="deny",
                    )
                )
            elif fault.endswith("permission"):
                url = catalog_url if fault == "catalog_permission" else package_url
                auth.permissions.add(
                    PermissionRule("oidc:*:alice", "tool.web_fetch", url, effect="deny")
                )
            elif fault == "catalog_remove":
                SkillRegistry(view.root).remove_catalog(catalog_url)
            elif fault == "catalog_changed":
                registry = SkillRegistry(view.root)
                state = registry._state()
                state["catalog_snapshots"][catalog_url]["skills"][0]["source"] = (
                    package_url + ".changed"
                )
                registry._write_state(state)
            else:
                changed = io.BytesIO()
                with (
                    zipfile.ZipFile(io.BytesIO(content)) as source_zip,
                    zipfile.ZipFile(changed, "w") as target_zip,
                ):
                    for name in source_zip.namelist():
                        target_zip.writestr(
                            name,
                            source_zip.read(name)
                            + (
                                b"changed instructions"
                                if name.endswith("SKILL.md")
                                else b""
                            ),
                        )
                return changed.getvalue()
        return content

    monkeypatch.setattr(SkillRegistry, "_remote_bytes", staticmethod(interrupt))
    response = mutate(body)
    assert not response["ok"], response
    assert not SkillRegistry(view.root).extensions.list()


@pytest.mark.parametrize("fault", ["cas", "publication", "revoked"])
def test_http_failed_update_preserves_prior_or_terminal_revocation_on_reload(
    remote_http, monkeypatch, fault
):
    view, _, _, _, _, _, entry, _, _, mutate = remote_http
    body = prepare(remote_http)
    assert mutate(body)["ok"]
    registry = SkillRegistry(view.root)
    prior = {
        path: path.read_bytes()
        for path in (registry.extensions.index_path, registry.extensions.lock_path)
    }

    def fail(*_args, **_kwargs):
        raise OSError("fake publication fault")

    if fault == "cas":
        monkeypatch.setattr(ContentAddressedArtifactStore, "store_bytes", fail)
    elif fault == "publication":
        monkeypatch.setattr(ExtensionRegistry, "_write_lock", fail)
    else:
        manifest = registry.extensions.verify("skills/code-helper")
        ExtensionRegistry(registry.extensions.root).record_revocation(
            "skills/code-helper",
            {
                "normalized_digest": manifest.provenance.digest,
                "granted_capabilities": [],
            },
        )
    assert not mutate(body)["ok"]
    restored = SkillRegistry(view.root)
    if fault == "revoked":
        assert (
            restored.extensions.get_record("skills/code-helper")["state"] == "revoked"
        )
        with pytest.raises(KeyError):
            restored.load("installed:code-helper")
        assert not mutate(body)["ok"]
    else:
        assert all(path.read_bytes() == previous for path, previous in prior.items())
        assert restored.load("installed:code-helper").digest == entry.digest


@pytest.mark.parametrize(
    "field", ["catalog_source", "package_source", "version", "digest"]
)
def test_http_fresh_nonce_cannot_install_changed_review(remote_http, field):
    view, _, _, _, _, _, _, connections, _, mutate = remote_http
    body = prepare(remote_http)
    count = len(connections)
    assert not mutate(body | {field: body[field] + ".changed"})["ok"]
    assert len(connections) == count
    assert not SkillRegistry(view.root).extensions.list()


@pytest.mark.parametrize("action", ["catalog_add", "catalog_refresh"])
@pytest.mark.parametrize("fault", ["human", "network"])
def test_http_catalog_authority_revalidated_after_tls_before_snapshot_publication(
    remote_http, monkeypatch, action, fault
):
    view, auth, _, _, catalog_url, _, _, _, _, mutate = remote_http
    if action == "catalog_refresh":
        prepare(remote_http)
    registry = SkillRegistry(view.root)
    before = registry.state_path.read_bytes() if registry.state_path.exists() else None
    original = SkillRegistry._remote_bytes

    def revoke(source, **kwargs):
        content = original(source, **kwargs)
        if fault == "human":
            with view.gate.store.operation_transaction() as db:
                db.execute("UPDATE governance_human_sessions SET status='REVOKED'")
        else:
            auth.permissions.add(
                PermissionRule(
                    "oidc:*:alice", "tool.web_fetch", catalog_url, effect="deny"
                )
            )
        return content

    monkeypatch.setattr(SkillRegistry, "_remote_bytes", staticmethod(revoke))
    assert not mutate(catalog_body(catalog_url, action))["ok"]
    if before is None:
        assert not registry.state_path.exists()
    else:
        assert registry.state_path.read_bytes() == before


def test_http_restarted_owners_preserve_catalog_installed_state_and_revocation(
    remote_http, monkeypatch
):
    view, auth, _, _, catalog_url, _, entry, connections, request, mutate = remote_http
    body = prepare(remote_http)
    assert mutate(body)["ok"]
    registry = SkillRegistry(view.root)
    manifest = registry.extensions.verify("skills/code-helper")
    registry.extensions.record_revocation(
        "skills/code-helper",
        {"normalized_digest": manifest.provenance.digest, "granted_capabilities": []},
    )
    store = GovernanceStore(Path(view.gate.store.db_path).parent)
    restored_auth = HumanSessionAuth(store, auth.provider, permissions=auth.permissions)
    restored = OperationsPlane(
        view.root,
        gate=ExecutionAuthorizationGate(store),
        health_loader=lambda: {"ok": True},
    )
    monkeypatch.setattr(operations, "_operations", restored)
    monkeypatch.setattr(human_sessions, "_configured_auth", restored_auth)
    count = len(connections)
    snapshot = request("/api/v1/control/operations")["data"]
    assert snapshot["skill_catalogs"] == [{"source": catalog_url, "remote": True}]
    assert len(connections) == count
    assert not mutate(body)["ok"]
    assert (
        SkillRegistry(view.root).extensions.get_record("skills/code-helper")["state"]
        == "revoked"
    )
    with pytest.raises(KeyError):
        SkillRegistry(view.root).load("installed:code-helper")
    assert not restored.gate.store.list_active_leases()
    assert entry.digest == manifest.provenance.digest


def test_http_package_metadata_cannot_change_reviewed_removal_target(
    remote_http, tmp_path
):
    from nous_runtime.control_plane.human_sessions import human_permission
    from nous_runtime.extensions import ExtensionInspector
    from tests.skills.test_remote_catalog import bundle
    from tests.skills.test_skill_registry import make_skill

    view, _, context, root, _, _, _, _, request, mutate = remote_http
    registry = SkillRegistry(view.root)
    victim = registry.install(make_skill(tmp_path / "victim", name="victim"))
    assert not human_permission(context, "control.skill_manage", "skill:victim")
    source = make_skill(tmp_path / "reviewed" / "code-helper")
    (source / "SKILL.md").write_text(
        (source / "SKILL.md")
        .read_text()
        .replace(
            "risk: low\n",
            "risk: low\nmetadata:\n  extension_id: skills/victim\n"
            "  authority: kernel_grant\n",
        )
    )
    manifest = ExtensionInspector().inspect(source)
    catalog = json.loads((root / "catalog.json").read_text())
    catalog["skills"][0].update(digest=manifest.provenance.digest)
    (root / "catalog.json").write_text(json.dumps(catalog))
    (root / "code-helper.zip").write_bytes(bundle(source))
    assert mutate(prepare(remote_http))["ok"]
    selected = SkillRegistry(view.root).load("installed:code-helper")
    assert selected.metadata["extension_id"] == manifest.extension_id
    assert selected.metadata["authority"] == "none"
    snapshot = request("/api/v1/control/operations")["data"]
    row = next(
        item
        for item in snapshot["skills"]
        if item["provider"] == "installed" and item["skill_id"] == "code-helper"
    )
    response = mutate(install_body(row) | {"action": "remove"})
    assert response["ok"], response
    restored = SkillRegistry(view.root)
    assert restored.extensions.get_record(manifest.extension_id) is None
    assert restored.load("installed:victim").digest == victim.digest
    assert ContentAddressedArtifactStore(restored.artifact_root).verify(
        victim.artifact_ref
    )
    assert not view.gate.store.list_active_leases()


@pytest.mark.parametrize("change", ["permission", "update"])
def test_http_remove_rechecks_authority_and_original_content_under_writer_fence(
    remote_http, tmp_path, monkeypatch, change
):
    from tests.skills.test_skill_registry import make_skill

    view, auth, _, _, _, _, _, _, request, mutate = remote_http
    assert mutate(prepare(remote_http))["ok"]
    row = next(
        item
        for item in request("/api/v1/control/operations")["data"]["skills"]
        if item["provider"] == "installed"
    )
    original = ExtensionRegistry.remove
    changed = []

    def intervene(owner, extension_id, **kwargs):
        if change == "permission":
            auth.permissions.add(
                PermissionRule(
                    "oidc:*:alice",
                    "control.skill_manage",
                    "skill:code-helper",
                    effect="deny",
                )
            )
        else:
            source = make_skill(tmp_path / "updated" / "code-helper", version="1.2.4")
            changed.append(SkillRegistry(view.root).install(source).digest)
        return original(owner, extension_id, **kwargs)

    monkeypatch.setattr(ExtensionRegistry, "remove", intervene)
    response = mutate(install_body(row) | {"action": "remove"})
    assert not response["ok"], response
    current = SkillRegistry(view.root).load("installed:code-helper")
    assert current.digest == (changed[0] if changed else row["digest"])
    assert not any(
        item["event_type"] == "skill.management.completed"
        and json.loads(item["evidence_json"])["action"] == "remove"
        for item in view.gate.store.operation_audit()
    )


def test_http_historical_duplicate_imports_are_visible_but_not_actionable(
    remote_http, tmp_path
):
    from tests.skills.test_skill_registry import make_skill

    view, _, _, _, _, _, _, connections, request, mutate = remote_http
    registry = SkillRegistry(view.root)
    legacy = tmp_path / "old-import.json"
    legacy.write_text(
        json.dumps(
            {
                "id": "code-helper",
                "description": "Owned historical import",
                "instruction": "Inspect original source",
            }
        )
    )
    registry.install(legacy)
    registry.extensions.install(make_skill(tmp_path / "code-helper"))
    before = registry.extensions.index_path.read_bytes()
    network_count = len(connections)
    data = request("/api/v1/control/operations")["data"]
    rows = [
        item
        for item in data["skills"]
        if item["provider"] == "installed" and item["skill_id"] == "code-helper"
    ]
    assert len(rows) == 2
    assert len({item["skill_key"] for item in rows}) == 2
    assert {item["identity_status"] for item in rows} == {"AMBIGUOUS"}
    for row in rows:
        for action in ("load", "enable", "disable", "remove"):
            result = mutate(install_body(row) | {"action": action})
            assert not result["ok"], result
    assert registry.extensions.index_path.read_bytes() == before
    assert len(connections) == network_count
    assert len(SkillRegistry(view.root).extensions.list()) == 2

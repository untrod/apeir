"""Existing SQLite readers must open their exact filesystem-selected database."""

from __future__ import annotations

import os
import shutil
import sqlite3

import pytest

from nous_runtime.connectors.adapters import SQLiteConnector
from nous_runtime.connectors.models import ConnectorRequest
from nous_runtime.ecosystem.manifest import CapabilityManifest
from nous_runtime.ecosystem.registry import CapabilityRegistry
from nous_runtime.governance.store import GovernanceStore
from nous_runtime.network.models import AgentNode
from nous_runtime.network.registry import NetworkRegistry
from nous_runtime.sqlite_runtime import SQLiteRuntime


@pytest.fixture(params=["#chosen", "?chosen", "%23chosen", " space-π"])
def selected_path(tmp_path, request):
    if os.name == "nt" and "?" in request.param:
        pytest.skip("Question marks are not legal Windows filename characters")
    return tmp_path / f"database{request.param}", tmp_path / "database"


def _governance_records(store, label):
    decision = {
        "decision_id": f"decision-{label}",
        "proposal_hash": "owned-proposal",
        "action_mode": "EXECUTE",
        "allowed": True,
    }
    approval = {
        "request_id": f"approval-{label}",
        "proposal_hash": "owned-proposal",
        "status": "PENDING",
    }
    lease = {
        "lease_id": f"lease-{label}",
        "proposal_hash": "owned-proposal",
        "status": "ACTIVE",
        "remaining_uses": 1,
    }
    assert store.save_decision(decision)
    assert store.save_approval_request(approval)
    assert store.save_lease(lease)
    return decision, approval, lease


def test_governance_authority_record_reads_keep_selected_database(
    tmp_path, selected_path
):
    selected, shadow = selected_path
    source = GovernanceStore(tmp_path / "source")
    _governance_records(source, "outside")
    shutil.copyfile(source.db_path, shadow)
    store = GovernanceStore(selected)
    before = shadow.read_bytes()
    assert store.get_decision("decision-outside") is None
    assert store.get_approval_request("approval-outside") is None
    assert store.get_lease("lease-outside") is None
    assert store.consume_lease("lease-outside", "owned-execution") == (False, 0)
    decision, approval, lease = _governance_records(store, "selected")
    assert store.get_decision(decision["decision_id"]) == decision
    assert store.get_approval_request(approval["request_id"]) == approval
    assert store.get_lease(lease["lease_id"]) == lease
    assert shadow.read_bytes() == before


def _items(database, label):
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE items (value TEXT)")
        db.execute("INSERT INTO items VALUES (?)", (label,))


def test_sqlite_runtime_reads_exact_file(selected_path):
    selected, shadow = selected_path
    _items(shadow, "outside")
    runtime = SQLiteRuntime(selected)
    with runtime.connect() as db:
        db.execute("CREATE TABLE items (value TEXT)")
        db.execute("INSERT INTO items VALUES ('selected')")
    before = shadow.read_bytes()
    with runtime.connect(readonly=True) as db:
        assert db.execute("SELECT value FROM items").fetchone()[0] == "selected"
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.execute("INSERT INTO items VALUES ('not-authorized')")
    assert runtime.explain_query_plan("SELECT value FROM items")
    assert shadow.read_bytes() == before


def test_sqlite_runtime_integrity_checks_selected_file(selected_path):
    selected, shadow = selected_path
    shadow.write_bytes(b"owned fake corrupt shadow")
    runtime = SQLiteRuntime(selected)
    with runtime.connect() as db:
        db.execute("CREATE TABLE items (value TEXT)")
    assert runtime.metrics()["integrity_status"] == "ok"
    assert shadow.read_bytes() == b"owned fake corrupt shadow"


def test_capability_registry_reads_selected_database(tmp_path, selected_path):
    selected, shadow = selected_path
    source = CapabilityRegistry(str(tmp_path / "source"))
    assert source.install(CapabilityManifest(name="outside"))
    shutil.copyfile(source.db_path, shadow)
    registry = CapabilityRegistry(str(selected))
    before = shadow.read_bytes()
    assert registry.list() == []
    assert registry.install(CapabilityManifest(name="selected"))
    assert registry.get("selected").name == "selected"
    assert registry.get("outside") is None
    assert shadow.read_bytes() == before


def test_legacy_network_registry_reads_selected_database(tmp_path, selected_path):
    selected, shadow = selected_path
    source = NetworkRegistry(str(tmp_path / "source"))
    assert source.register(AgentNode(id="outside"))
    shutil.copyfile(source.db_path, shadow)
    registry = NetworkRegistry(str(selected))
    before = shadow.read_bytes()
    assert registry.list() == []
    assert registry.register(AgentNode(id="selected"))
    assert registry.get("selected").id == "selected"
    assert registry.get("outside") is None
    assert shadow.read_bytes() == before


def test_sqlite_connector_keeps_explicit_database(selected_path):
    selected, shadow = selected_path
    _items(shadow, "outside")
    _items(selected, "selected")
    before = shadow.read_bytes()
    result = SQLiteConnector(selected).execute(
        ConnectorRequest(
            "sqlite", "query", "owned-workspace", {"sql": "SELECT value FROM items"}
        ),
        None,
    )
    assert result.ok is True
    assert result.items == ({"value": "selected"},)
    assert shadow.read_bytes() == before

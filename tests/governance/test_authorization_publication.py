"""An authorization and its chained evidence are one durable publication."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from nous_runtime.governance import ExecutionAuthorizationGate
from nous_runtime.governance.contracts import ActionProposal, AuthorizationContext
from nous_runtime.governance import store as stores


def evaluate(governance, *, allowed=False):
    proposal = ActionProposal(
        action_type="capability.execute",
        capability_id="system.echo",
        side_effect_class="read_only",
        reversibility="reversible",
    )
    context = AuthorizationContext(
        subject_type="user", subject_id="", authn_confidence=0.9
    )
    gate = ExecutionAuthorizationGate(store=governance)
    if allowed:
        decision = gate._finalize_decision(
            proposal, context, gate._execute(proposal, context, None)
        )
    else:
        decision = gate.evaluate(proposal, context)
    return proposal, decision


def test_one_decision_has_one_committed_publication(tmp_path, monkeypatch):
    governance = stores.GovernanceStore(tmp_path)
    connect = sqlite3.connect
    boundaries = []

    def traced(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connection.set_trace_callback(
            lambda statement: (
                boundaries.append(statement.strip().upper())
                if statement.strip().upper() in {"COMMIT", "ROLLBACK"}
                else None
            )
        )
        return connection

    with monkeypatch.context() as trace:
        trace.setattr(stores.sqlite3, "connect", traced)
        proposal, decision = evaluate(governance, allowed=True)
    assert boundaries == ["COMMIT"]
    assert decision.action_mode == "EXECUTE"
    assert decision.allowed is True
    assert governance.get_proposal(proposal.proposal_hash) == proposal.to_dict()
    assert governance.get_decision(decision.decision_id) == decision.to_dict()
    assert governance.verify_audit_chain()
    assert len(governance.operation_audit()) == 1


@pytest.mark.parametrize("stage", ["proposal", "decision", "audit", "commit"])
def test_failed_publication_rolls_back_and_never_returns_authority(
    tmp_path, monkeypatch, stage
):
    governance = stores.GovernanceStore(tmp_path)
    connect = sqlite3.connect
    closed = []

    class Connection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if stage != "commit" and (
                "INSERT" in sql.upper()
                and "governance_" + ("audit" if stage == "audit" else stage + "s")
                in sql
            ):
                raise sqlite3.OperationalError("injected publication failure")
            return super().execute(sql, *args, **kwargs)

        def commit(self):
            if stage == "commit":
                raise sqlite3.OperationalError("injected commit failure")
            return super().commit()

        def close(self):
            closed.append(self)
            return super().close()

    def faulty(*args, **kwargs):
        return connect(*args, factory=Connection, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(stores.sqlite3, "connect", faulty)
        proposal, decision = evaluate(governance, allowed=True)
    assert closed
    assert decision.action_mode == "DENY"
    assert decision.allowed is False
    assert decision.reason_code.endswith("STORE_UNAVAILABLE")
    assert governance.get_proposal(proposal.proposal_hash) is None
    assert governance.get_decision(decision.decision_id) is None
    assert governance.operation_audit() == []
    with stores._db_connect(governance.db_path, readonly=True) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_independent_writers_preserve_original_chain_and_bindings(tmp_path):
    writers = [stores.GovernanceStore(tmp_path) for _ in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(evaluate, writers))
    reopened = stores.GovernanceStore(tmp_path)
    audits = reopened.operation_audit()
    assert len(audits) == 4
    assert reopened.verify_audit_chain()
    assert {row["decision_id"] for row in audits} == {
        decision.decision_id for _, decision in records
    }
    for proposal, decision in records:
        assert reopened.get_proposal(proposal.proposal_hash) is not None
        assert reopened.get_decision(decision.decision_id) == decision.to_dict()


def test_uncertain_commit_is_denied_without_retrying_publication(tmp_path, monkeypatch):
    governance = stores.GovernanceStore(tmp_path)
    connect = sqlite3.connect
    commits = []

    class Connection(sqlite3.Connection):
        def commit(self):
            super().commit()
            commits.append(True)
            raise sqlite3.OperationalError("response lost after commit")

    def uncertain(*args, **kwargs):
        return connect(*args, factory=Connection, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(stores.sqlite3, "connect", uncertain)
        proposal, result = evaluate(governance, allowed=True)
    assert result.action_mode == "DENY"
    assert result.allowed is False
    assert commits == [True]
    assert governance.get_proposal(proposal.proposal_hash) is not None
    assert len(governance.operation_audit()) == 1
    assert governance.verify_audit_chain()

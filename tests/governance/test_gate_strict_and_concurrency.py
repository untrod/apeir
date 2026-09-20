import threading

from nous_runtime.capability import resolver
from nous_runtime.governance.contracts import ApprovalResponse, ActionProposal
from nous_runtime.governance.lease import LeaseManager
from nous_runtime.governance.store import GovernanceStore


def test_execute_capability_blocks_gate_exception_in_strict_mode(monkeypatch):
    monkeypatch.setenv("NOUS_RUNTIME_MODE", "strict")
    monkeypatch.setattr(resolver, "resolve_capability", lambda capability_id: resolver.ResolutionResult(
        capability_id=capability_id,
        provider_id="provider-a",
        provider_name="Provider A",
        resolved=True,
    ))

    class BrokenGate:
        def evaluate(self, proposal, context):
            raise RuntimeError("store unavailable")

    monkeypatch.setattr("nous_runtime.governance.get_gate", lambda: BrokenGate())
    result = resolver.execute_capability("system.echo", message="hello")
    assert result.ok is False
    assert result.error_code == "NOUS_GOVERNANCE_UNAVAILABLE"


def test_one_use_lease_concurrent_consumption_allows_one_winner(tmp_path):
    gov_store = GovernanceStore(tmp_path)
    prop = ActionProposal(capability_id="tool.file_read", action_type="capability.execute", created_at="2026-01-01T00:00:00Z")
    response = ApprovalResponse(request_id="req", proposal_hash=prop.proposal_hash, decision="APPROVED", approver_id="alice")
    lease = LeaseManager(gov_store).issue(prop, response, max_uses=1)
    results = []
    lock = threading.Lock()

    def consume(index):
        ok, remaining = gov_store.consume_lease(lease.lease_id, f"exec-{index}")
        with lock:
            results.append((ok, remaining))

    threads = [threading.Thread(target=consume, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(1 for ok, _ in results if ok) == 1
    assert gov_store.get_lease(lease.lease_id)["status"] == "EXHAUSTED"

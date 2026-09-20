from nous_runtime.intelligence.reliability.executor import execute_provider


def test_provider_execute_blocks_gate_exception_in_strict(monkeypatch):
    monkeypatch.setenv("NOUS_RUNTIME_MODE", "strict")

    class BrokenGate:
        def evaluate(self, proposal, context):
            raise RuntimeError("gate unavailable")

    monkeypatch.setattr("nous_runtime.governance.get_gate", lambda: BrokenGate())
    result = execute_provider("provider-a", "system.echo", payload={"message": "hello"})
    assert result.success is False
    assert result.provider_error_code == "NOUS_GOVERNANCE_UNAVAILABLE"


def test_device_pc_exec_requires_approval_in_strict(monkeypatch):
    monkeypatch.setenv("NOUS_RUNTIME_MODE", "strict")
    result = execute_provider(
        "pc_agent",
        "device.pc.exec",
        payload={"command": "whoami", "_authn_confidence": 0.95},
    )
    assert result.success is False
    assert result.provider_error_code in {"NOUS_GOVERNANCE_ASK_APPROVAL", "NOUS_GOVERNANCE_DENY"}


def test_provider_execute_compatibility_continues_in_development(monkeypatch):
    monkeypatch.setenv("NOUS_RUNTIME_MODE", "development")

    class BrokenGate:
        def evaluate(self, proposal, context):
            raise RuntimeError("gate unavailable")

    monkeypatch.setattr("nous_runtime.governance.get_gate", lambda: BrokenGate())
    result = execute_provider("missing-provider", "system.echo", payload={"message": "hello"})
    assert result.success is False
    assert result.provider_error_code == "NOUS_PROVIDER_NOT_FOUND"

from nous_runtime.governance.runtime_mode import (
    GovernanceRuntimeMode,
    mode_policy,
    resolve_runtime_mode,
    should_fail_closed,
)


def test_local_cli_defaults_to_development(monkeypatch):
    monkeypatch.delenv("NOUS_RUNTIME_MODE", raising=False)
    monkeypatch.delenv("NOUS_ENV", raising=False)
    assert resolve_runtime_mode(surface="local_cli") == GovernanceRuntimeMode.DEVELOPMENT
    assert not should_fail_closed(surface="local_cli")


def test_server_defaults_to_production(monkeypatch):
    monkeypatch.delenv("NOUS_RUNTIME_MODE", raising=False)
    monkeypatch.delenv("NOUS_ENV", raising=False)
    policy = mode_policy(surface="server")
    assert policy.mode == GovernanceRuntimeMode.PRODUCTION
    assert policy.fail_closed
    assert policy.audit_required


def test_explicit_strict_mode_is_fail_closed(monkeypatch):
    monkeypatch.setenv("NOUS_RUNTIME_MODE", "strict")
    assert resolve_runtime_mode(surface="local_cli") == GovernanceRuntimeMode.STRICT
    assert should_fail_closed(surface="local_cli")

"""Control refusal stays fail-closed and exposes only bounded reason codes."""

import pytest

from nous_runtime.tools.process_session import ProcessSessionStore


@pytest.mark.parametrize(
    ("state", "error", "reason"),
    [
        (
            "RECOVERY_REQUIRED",
            "process host state is missing",
            "host_record_unavailable",
        ),
        (
            "RECOVERY_REQUIRED",
            "running process host identity cannot be verified",
            "os_identity_unverified",
        ),
        (
            "RECOVERY_REQUIRED",
            "process identity changed",
            "process_identity_mismatch",
        ),
        ("EXITED", "", "not_running"),
        ("LOST", "OWNED_BENIGN_UNTRUSTED_HOST_TEXT", "host_reported_error"),
    ],
)
def test_control_refusal_reports_reason_without_dispatch_or_raw_host_text(
    monkeypatch, state, error, reason
):
    store = object.__new__(ProcessSessionStore)
    observations = []

    def status(session_id):
        observations.append(session_id)
        return {"state": state, "error": error}

    monkeypatch.setattr(store, "status", status)
    monkeypatch.setattr(
        store,
        "_directory",
        lambda *_: pytest.fail("Unqualified control must not publish a request"),
    )
    with pytest.raises(ValueError, match="process session is not running") as refused:
        store.kill("ps_owned")
    assert f"reason={reason}" in str(refused.value)
    assert "OWNED_BENIGN_UNTRUSTED_HOST_TEXT" not in str(refused.value)
    assert observations == ["ps_owned"]

"""Developer diagnostics coverage for Runtime Foundation."""

from nous_runtime.cli.doctor import format_report, run_diagnostics


def test_doctor_reports_all_runtime_foundation_contracts():
    report = run_diagnostics()
    foundation = {
        check.name: check
        for check in report.checks
        if check.section == "Runtime Foundation"
    }

    assert set(foundation) == {
        "Error Model",
        "Runtime State",
        "Event Envelope",
        "Artifact Registry",
    }
    assert all(check.status == "pass" for check in foundation.values())

    rendered = format_report(report)
    assert "Runtime Foundation" in rendered
    assert "PASS Error Model: OK" in rendered
    assert "PASS Artifact Registry: OK" in rendered

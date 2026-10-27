"""Exercise the native probe driver with real source CLI child processes."""

import sys
from pathlib import Path

from scripts.ci.probe_native_workflow import qualify


def test_probe_checks_real_cli_schema_history_and_missing_handler(
    tmp_path, monkeypatch
):
    # Source-process validation of the driver, not a Windows EXE qualification.
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[2]))
    result = qualify((sys.executable, "-m", "nous_runtime.cli.main"), tmp_path)
    assert result["cli_process_invocations"] == 9
    assert result["workflow_cli_process_invocations"] == 8
    assert result["command_discovery"] == "PASS"
    assert len(result["command_groups_checked"]) == 10
    assert result["schema_validation"] == "PASS"
    assert result["restart_history_same_id"]
    assert result["idempotent_submission_same_id"]
    assert result["unbound_action_rejected"]
    assert result["external_model_calls"] == 0
    assert list(tmp_path.iterdir()) == []

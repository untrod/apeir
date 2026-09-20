from __future__ import annotations

import sys
import pytest

from nous_runtime.kernel.sandbox import ProcessSandbox, SandboxPolicy


@pytest.mark.parametrize("require_strong", [True, False])
def test_untrusted_process_fails_before_start_without_strong_backend(
    tmp_path, monkeypatch, require_strong
):
    monkeypatch.setattr(
        "nous_runtime.kernel.windows_sandbox.executable_path", lambda: None
    )
    marker = tmp_path / "must-not-exist.txt"
    policy = SandboxPolicy(
        executable=sys.executable,
        args=["-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('bad')"],
        working_dir=str(tmp_path),
        read_allowed_paths=[str(tmp_path)],
        write_allowed_paths=[str(tmp_path)],
        network_allowed=False,
        isolation_level="strict",
        require_strong_isolation=require_strong,
    )

    result = ProcessSandbox(policy).run()

    assert not result.success
    assert result.availability_state == "unavailable"
    assert result.security_grade in {"resource_only", "soft_limits"}
    assert "STRICT_SANDBOX_UNAVAILABLE" in result.stderr
    assert "filesystem_scope" in result.unenforced_controls
    assert not marker.exists()


def test_security_report_never_labels_current_backend_strong():
    from unittest.mock import patch

    with patch("nous_runtime.kernel.windows_sandbox.executable_path", return_value=None):
        report = ProcessSandbox(
            SandboxPolicy(executable=sys.executable)
        ).security_report()

    assert report["strong"] is False
    assert "network_egress" in report["unenforced_controls"]

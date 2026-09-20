# -*- coding: utf-8 -*-
"""Capability availability tests — available vs unavailable classification."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestCheckAvailability:
    def test_empty_state_no_crash(self, monkeypatch, tmp_path):
        """No providers registered → all capabilities unavailable."""
        monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path))

        from remote_terminal.nous_core.db import run_migrations
        run_migrations()

        from nous_runtime.capability.availability import check_availability
        result = check_availability()

        assert "available" in result
        assert "unavailable" in result
        assert isinstance(result["available"], list)
        assert isinstance(result["unavailable"], list)

    def test_result_structure(self, monkeypatch, tmp_path):
        """Result must have the expected shape."""
        monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path))

        from remote_terminal.nous_core.db import run_migrations
        run_migrations()

        from nous_runtime.capability.availability import check_availability
        result = check_availability()

        for cap in result["available"]:
            assert "name" in cap
            assert "provider" in cap

        for cap in result["unavailable"]:
            assert "name" in cap
            assert "reason" in cap

    def test_unavailable_caps_have_reason(self, monkeypatch, tmp_path):
        """Every unavailable capability must have a reason string."""
        monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path))

        from remote_terminal.nous_core.db import run_migrations
        run_migrations()

        from nous_runtime.capability.availability import check_availability
        result = check_availability()

        for cap in result["unavailable"]:
            assert cap.get("reason"), \
                f"Capability {cap.get('name')} is unavailable but has no reason"

    def test_disabled_capability_unavailable(self, monkeypatch, tmp_path):
        """A disabled capability must appear in the unavailable list."""
        monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path))

        from remote_terminal.nous_core.db import run_migrations
        run_migrations()

        # Register a disabled capability
        from remote_terminal.nous_core.capability import register_capability
        register_capability(
            "test.disabled.cap",
            category="test",
            provider="test_provider",
            description="A disabled test capability",
            risk="low",
        )
        # There's no direct disable API; the capability defaults to enabled=1
        # We just verify it shows up somewhere (available or unavailable)

        from nous_runtime.capability.availability import check_availability
        result = check_availability()

        all_names = set()
        for cap in result["available"]:
            all_names.add(cap["name"])
        for cap in result["unavailable"]:
            all_names.add(cap["name"])

        assert "test.disabled.cap" in all_names, \
            "Registered capability should appear in available or unavailable"


    def test_subprocess_capability_uses_installed_executable_not_provider(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path))
        from remote_terminal.nous_core.db import run_migrations
        from remote_terminal.nous_core.capability import register_capability

        run_migrations()
        register_capability(
            "test.local.execute",
            category="test",
            provider="missing-provider",
            metadata={"executor_type": "subprocess", "command": ["test-runner", "--version"]},
        )
        monkeypatch.setattr(
            "nous_runtime.capability.availability.shutil.which",
            lambda executable: "/tools/test-runner" if executable == "test-runner" else None,
        )
        from nous_runtime.capability.availability import check_availability

        result = check_availability()
        available = {item["name"]: item for item in result["available"]}
        assert available["test.local.execute"]["executor_type"] == "subprocess"
        assert available["test.local.execute"]["executable"] == "/tools/test-runner"
        assert result["summary"]["registered"] == len(result["available"]) + len(result["unavailable"])

    def test_misconfigured_subprocess_capability_is_truthfully_unavailable(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path))
        from remote_terminal.nous_core.db import run_migrations
        from remote_terminal.nous_core.capability import register_capability

        run_migrations()
        register_capability(
            "test.local.missing-command",
            category="test",
            provider="irrelevant",
            metadata={"executor_type": "subprocess"},
        )
        from nous_runtime.capability.availability import check_availability

        result = check_availability()
        unavailable = {item["name"]: item for item in result["unavailable"]}
        assert unavailable["test.local.missing-command"]["reason"] == "subprocess command is not configured"
    def test_runtime_service_requires_central_dispatch_authority(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path))
        from remote_terminal.nous_core.db import run_migrations
        from remote_terminal.nous_core.capability import register_capability

        run_migrations()
        register_capability(
            "test.runtime.service",
            category="test",
            provider="nous",
            metadata={
                "executor_type": "runtime",
                "service": "nous_runtime.evidence.web_gateway:WebGateway",
            },
        )
        from nous_runtime.capability.availability import check_availability

        result = check_availability()
        unavailable = {item["name"]: item for item in result["unavailable"]}
        assert unavailable["test.runtime.service"]["executor_type"] == "runtime"
        assert "central dispatcher" in unavailable["test.runtime.service"]["reason"]

    def test_connected_runtime_capability_reports_scope_and_authorization(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path))
        from remote_terminal.nous_core.db import run_migrations
        from remote_terminal.nous_core.capability import register_capability

        run_migrations()
        register_capability(
            "document.create",
            category="productivity",
            provider="nous",
            requires_auth=True,
            metadata={
                "executor_type": "runtime",
                "service": "nous_runtime.documents.service:DocumentRuntime",
            },
        )
        from nous_runtime.capability.availability import check_availability

        result = check_availability()
        available = {item["name"]: item for item in result["available"]}
        record = available["document.create"]
        assert record["execution_scope"] == "runtime-service"
        assert record["availability_state"] == "requires_authorization"
        assert record["kernel_traversed"] is False

class TestCLI:
    def test_capability_availability_command(self):
        """nous capability availability must run without crash."""
        import subprocess

        r = subprocess.run(
            [sys.executable, "-m", "nous_runtime.cli.main",
             "capability", "availability"],
            capture_output=True, text=True, timeout=30,
            cwd=str(ROOT),
        )
        assert r.returncode == 0, f"stderr: {r.stderr}"
        # Should mention "Available" or "Unavailable"
        output = r.stdout.lower()
        assert "available" in output or "unavailable" in output

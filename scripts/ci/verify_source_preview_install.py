"""Exercise the installed public CLI outside the checkout, without model access.

Run with the fresh base-wheel consumer's isolated Python. This is Linux/POSIX
source qualification, not native Desktop, model or execution qualification.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def qualify() -> dict[str, object]:
    import nous_runtime

    if "site-packages" not in Path(nous_runtime.__file__).parts:
        raise RuntimeError("Source checkout imports cannot qualify wheel installation")
    if os.name != "posix":
        raise RuntimeError("This source startup qualification requires POSIX signals")
    entry = Path(sys.executable).parent / "apeir"
    command = [sys.executable, "-I", str(entry)]
    with tempfile.TemporaryDirectory(prefix="apeir-source-startup-") as directory:
        root = Path(directory)
        workspace = root / "project"
        config = workspace / ".nous" / "providers.json"
        config.parent.mkdir(parents=True)
        config.write_text(
            json.dumps(
                {
                    "never-load": {
                        "kind": "openai-compatible",
                        "model": "never-invoke",
                        "endpoint": "https://provider.example.invalid/v1/chat/completions",
                        "credential_ref": "env:APEIR_FAKE_ONLY_NEVER_RESOLVE",
                    }
                }
            ),
            encoding="utf-8",
        )
        original = config.read_bytes()
        token_path = root / "session" / "runtime.token"
        environment = dict(os.environ)
        for name in (
            "NOUS_API_TOKEN",
            "NOUS_AUTH_TOKEN",
            "NOUS_NO_INTELLIGENCE",
            "NOUS_KERNEL_ENDPOINT",
            "PYTHONPATH",
        ):
            environment.pop(name, None)
        environment.update(
            NOUS_WORKSPACE_ROOT=str(workspace),
            NOUS_DATA_DIR=str(root / "capabilities"),
            APEIR_STATE_DIR=str(root / "state"),
            NOUS_RUNTIME_MODE="production",
            NOUS_SESSION_TOKEN_FILE=str(token_path),
        )
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        arguments = ["runtime-api", "start", "--port", str(port)]
        refused = subprocess.run(
            command + arguments,
            cwd=workspace,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert refused.returncode == 1
        assert "NOUS_KERNEL_ENDPOINT is required" in refused.stderr
        assert not token_path.exists()

        def call(path, body=None, *, authenticated=True):
            headers = {"Content-Type": "application/json"}
            if authenticated:
                headers["Authorization"] = "Bearer " + token_path.read_text().strip()
            request = Request(
                f"http://127.0.0.1:{port}" + path,
                data=json.dumps(body).encode() if body is not None else None,
                headers=headers,
            )
            with urlopen(request, timeout=5) as response:
                return json.load(response)

        # Logs and session material stay in this private temporary directory;
        # only the explicit, content-free report is eligible for publication.
        with (root / "runtime.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                command + ["--no-intelligence"] + arguments,
                cwd=workspace,
                env=environment,
                stdout=log,
                stderr=log,
            )
            try:
                deadline = time.monotonic() + 10
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("Installed model-free public API exited")
                    try:
                        health = call("/api/v1/health/detailed")["data"]
                        break
                    except (URLError, FileNotFoundError, TimeoutError):
                        if time.monotonic() >= deadline:
                            raise RuntimeError(
                                "Installed public API did not become ready"
                            )
                        time.sleep(0.02)
                assert health["intelligence_mode"] == "disabled"
                assert health["provider_count"] == 0
                assert health["kernel"]["ready"] is False
                assert call("/api/v1/workspace/status")["data"]["path"] == str(
                    workspace
                )
                try:
                    call("/api/v1/providers", authenticated=False)
                except HTTPError as denied:
                    assert denied.code == 401
                    denied.close()
                else:
                    raise AssertionError("Unauthenticated Provider access was accepted")
                blocked = call(
                    "/api/v1/models/test", {"model_id": "never-load/never-invoke"}
                )["data"]
                assert blocked["healthy"] is False
                assert blocked["tokens_used"] is None and blocked["cost_usd"] is None
                assert config.read_bytes() == original
                assert token_path.stat().st_mode & 0o077 == 0
                status = subprocess.run(
                    command
                    + [
                        "runtime-api",
                        "status",
                        "--url",
                        f"http://127.0.0.1:{port}",
                        "--json",
                    ],
                    cwd=workspace,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                assert status.returncode == 0 and json.loads(status.stdout)["ok"]
            finally:
                if process.poll() is None:
                    process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                    raise RuntimeError(
                        "Public API did not close on interrupt"
                    ) from None
        assert process.returncode == 0 and not token_path.exists()
        with socket.socket() as probe:
            assert probe.connect_ex(("127.0.0.1", port)) != 0
    return {
        "public_cli_model_free_startup": "PASS",
        "production_model_startup_without_kernel": "BLOCKED",
        "unauthenticated_access": "DENIED",
        "model_usage_without_execution": "UNKNOWN",
        "saved_provider_configuration_unchanged": True,
        "session_owner_only": True,
        "interrupt_exit_code": 0,
        "session_revoked": True,
        "listener_closed": True,
        "startup_platform": sys.platform,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    arguments = parser.parse_args()
    result = qualify()
    arguments.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))

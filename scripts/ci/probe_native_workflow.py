"""Qualify pure Workflow contracts through the actual packaged Runtime CLI."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Sequence


def qualify(command: Sequence[str], workspace: Path) -> dict:
    """Use owned fixture data only; no Provider, command handler or device effects."""
    with tempfile.TemporaryDirectory(
        prefix="workflow-cli-", dir=workspace
    ) as directory:
        root = Path(directory)
        environment = {**os.environ, "NOUS_WORKSPACE_ROOT": directory}
        definition = {
            "workflow_id": "native.workflow.contract",
            "version": "1",
            "trigger": "manual",
            "steps": [
                {"step_id": "compute", "step_type": "transform", "params": {"value": 3}}
            ],
            "inputs_schema": {
                "type": "object",
                "properties": {"count": {"type": "integer"}},
                "required": ["count"],
                "additionalProperties": False,
            },
            "outputs_schema": {
                "type": "object",
                "properties": {
                    "compute": {
                        "type": "object",
                        "properties": {"value": {"type": "integer"}},
                        "required": ["value"],
                    }
                },
                "required": ["compute"],
            },
        }
        path = root / "workflow.json"
        path.write_text(json.dumps(definition), encoding="utf-8")
        help_result = subprocess.run(
            [*command, "--no-intelligence", "--help"],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        expected_groups = {
            "connector",
            "extension",
            "plugin",
            "library",
            "workflow",
            "automation",
            "work",
            "tools",
            "skill",
            "web",
        }
        actual_groups = set(re.findall(r"(?m)^\s+([a-z][a-z-]*)\s", help_result.stdout))
        missing = expected_groups - actual_groups
        if help_result.returncode or missing:
            raise RuntimeError(
                "Packaged Runtime command groups missing: " + ", ".join(sorted(missing))
            )
        calls = 1

        def invoke(*arguments: str, rejected: bool = False):
            nonlocal calls
            process = subprocess.run(
                [*command, "--no-intelligence", "workflow", *arguments],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                check=False,
            )
            calls += 1
            if rejected:
                diagnostic = process.stdout + process.stderr
                if (
                    process.returncode == 0
                    or "Workflow inputs" not in diagnostic
                    or "schema" not in diagnostic
                    or "PRIVATE_FIXTURE_VALUE" in diagnostic
                    or "Traceback" in diagnostic
                ):
                    raise RuntimeError("Packaged CLI input-contract rejection failed")
                return None
            if process.returncode:
                # All inputs are deterministic, non-secret qualification fixtures.
                raise RuntimeError(
                    f"Packaged Workflow CLI failed: {process.stderr[-4000:]}"
                )
            return json.loads(process.stdout)

        invoke("validate", str(path), "--json")
        invoke("register", str(path), "--json")
        arguments = (
            "run",
            definition["workflow_id"],
            "--version",
            "1",
            "--inputs",
            '{"count":1}',
            "--idempotency-key",
            "original",
            "--json",
        )
        original = invoke(*arguments)
        if (
            original["state"] != "completed"
            or original["outputs"]["compute"]["value"] != 3
        ):
            raise RuntimeError("Packaged Workflow output contract failed")
        invoke(
            "run",
            definition["workflow_id"],
            "--version",
            "1",
            "--inputs",
            '{"count":"PRIVATE_FIXTURE_VALUE"}',
            "--json",
            rejected=True,
        )
        restored = invoke("show", original["run_id"], "--json")
        repeated = invoke(*arguments)
        if (
            restored["run_id"] != original["run_id"]
            or repeated["run_id"] != original["run_id"]
        ):
            raise RuntimeError("Packaged Workflow lost its original Run identity")
        unsupported = {
            **definition,
            "workflow_id": "native.workflow.unsupported",
            "inputs_schema": {},
            "outputs_schema": {},
            "steps": [
                {
                    "step_id": "missing",
                    "step_type": "transform",
                    "action": "missing.host.handler",
                }
            ],
        }
        path.write_text(json.dumps(unsupported), encoding="utf-8")
        invoke("register", str(path), "--json")
        failed = invoke("run", unsupported["workflow_id"], "--version", "1", "--json")
        if failed["state"] != "failed" or "no workflow handler" not in failed["error"]:
            raise RuntimeError("Packaged Workflow accepted an unbound action")
        return {
            "scope": "actual CLI pure Workflow; no model, command handler or physical effect",
            "cli_process_invocations": calls,
            "workflow_cli_process_invocations": calls - 1,
            "command_discovery": "PASS",
            "command_groups_checked": sorted(expected_groups),
            "schema_validation": "PASS",
            "invalid_input_rejected": True,
            "private_fixture_not_echoed": True,
            "original_run_id": original["run_id"],
            "restart_history_same_id": True,
            "idempotent_submission_same_id": True,
            "unbound_action_rejected": True,
            "external_model_calls": 0,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sidecar", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    result = qualify((str(args.sidecar.resolve(strict=True)),), args.workspace)
    args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

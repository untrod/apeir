"""Real provider acceptance for the P1-P5 collaborative project path.

The caller supplies credentials through the process environment.  This script
never reads a credential from arguments and never writes one to its report.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


REQUIRED_FILES = (
    "nous-p1-p5-demo/README.md",
    "nous-p1-p5-demo/wordstats.py",
    "nous-p1-p5-demo/tests/test_wordstats.py",
    "nous-p1-p5-demo/REPORT.md",
    "nous-p1-p5-demo/PAPER.md",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--provider-config", required=True)
    parser.add_argument("--model", default="deepseek/deepseek-chat")
    parser.add_argument("--kernel-endpoint", default="tcp://127.0.0.1:8771")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    provider_config = Path(args.provider_config).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    nous_dir = workspace / ".nous"
    nous_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(provider_config, nous_dir / "providers.json")
    (workspace / "workspace.json").write_text(
        json.dumps(
            {
                "workspace_id": "p1-p5-acceptance",
                "name": "P1-P5 acceptance",
                "root": str(workspace),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    os.environ["NOUS_WORKSPACE_ROOT"] = str(workspace)
    os.environ["NOUS_KERNEL_ENDPOINT"] = args.kernel_endpoint
    os.environ.setdefault("NOUS_ALLOWED_CREDENTIALS", "DEEPSEEK_API_KEY")

    from nous_runtime.chat import ChatRequest, ChatRuntime

    request_id = "p1-p5-deepseek-project"
    prompt = """
Create a complete small Python project in the selected workspace directory
`nous-p1-p5-demo`. This is an explicitly authorized workspace mutation.

Use Nous collaborative execution: manager plus independent implementation,
quality, report, and paper work lanes, followed by reviewer verification.
Create all of these exact files with governed workspace tools. Use one
`write_file` call per file so each receipt remains small and independently
verifiable:

- `nous-p1-p5-demo/wordstats.py`: a dependency-free CLI and reusable functions
  that count logical lines, whitespace-separated words, and non-whitespace
  characters in UTF-8 text. Define logical lines as zero for empty input and
  otherwise `len(text.splitlines())`; define non-whitespace characters as
  `sum(not character.isspace() for character in text)`.
- `nous-p1-p5-demo/tests/test_wordstats.py`: pytest tests for empty text,
  multilingual text, and CLI JSON output.
- `nous-p1-p5-demo/README.md`: install-free usage and test commands.
- `nous-p1-p5-demo/REPORT.md`: professional engineering report covering scope,
  architecture, validation, limitations, and reproducibility.
- `nous-p1-p5-demo/PAPER.md`: concise paper with abstract, method, experiment,
  results, limitations, and conclusion. Do not invent citations; explicitly say
  the acceptance experiment used no external literature.

After writing, run the bounded command `python -m pytest
nous-p1-p5-demo/tests -q`, inspect the result, and only report completion when
the tool receipts and tests confirm it. Keep implementation simple and portable.
""".strip()

    response = ChatRuntime(str(workspace)).send(
        ChatRequest(
            prompt,
            "p1-p5-acceptance",
            "local",
            model_id=args.model,
            agent_mode="agent",
            request_id=request_id,
        )
    )

    project = workspace / "nous-p1-p5-demo"
    missing = [
        item
        for item in REQUIRED_FILES
        if not (workspace / item).is_file() or (workspace / item).stat().st_size == 0
    ]
    test_run = subprocess.run(
        [sys.executable, "-m", "pytest", str(project / "tests"), "-q"],
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    runtime_result = dict(response.data.get("result") or {})
    execution = dict(runtime_result.get("execution") or {})
    product = dict(execution.get("result") or {})
    collaboration = dict(product.get("collaboration") or {})
    lanes = list(collaboration.get("lanes") or [])
    review = dict(collaboration.get("review") or {})

    from nous_runtime.events import EventStream

    events = EventStream(str(workspace)).load_events(request_id)
    event_types = [event.event_type for event in events]
    report = {
        "request_id": request_id,
        "runtime_status": response.status,
        "trace_id": response.trace_id,
        "model": args.model,
        "collaboration_enabled": bool(collaboration.get("enabled")),
        "lane_count": len(lanes),
        "lanes": [
            {
                "lane_id": item.get("lane_id", ""),
                "role": item.get("role", ""),
                "provider_id": item.get("provider_id", ""),
                "model_id": item.get("model_id", ""),
                "usage": item.get("usage", {}),
                "cost_usd": item.get("cost_usd", 0.0),
                "latency_ms": item.get("latency_ms", 0),
            }
            for item in lanes
        ],
        "review_approved": bool(review.get("approved")),
        "review_receipts_verified": bool(review.get("receipts_verified")),
        "review_verdict": str(review.get("verdict") or "")[:2_000],
        "review_model": review.get("model_id", ""),
        "required_files": list(REQUIRED_FILES),
        "missing_files": missing,
        "independent_pytest_exit_code": test_run.returncode,
        "independent_pytest_tail": (test_run.stdout + test_run.stderr)[-2_000:],
        "event_count": len(events),
        "event_types": event_types,
        "tool_step_count": len(product.get("agent_steps") or []),
        "tool_steps": [
            {
                "tool": item.get("tool", ""),
                "ok": bool((item.get("result") or {}).get("ok")),
                "error": str((item.get("result") or {}).get("error") or "")[:500],
                "file_count": int((item.get("result") or {}).get("file_count") or 0),
                "exit_code": (item.get("result") or {}).get("exit_code"),
            }
            for item in product.get("agent_steps") or []
        ],
        "internal_protocol_exposed": (
            "NOUS_TOOL_CALL" in response.message
            or "NOUS_TOOL_RESULT" in response.message
        ),
    }
    (workspace / "P1-P5-ACCEPTANCE.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "runtime_status",
                    "collaboration_enabled",
                    "lane_count",
                    "review_approved",
                    "missing_files",
                    "independent_pytest_exit_code",
                    "event_count",
                    "tool_step_count",
                    "internal_protocol_exposed",
                )
            },
            ensure_ascii=False,
        )
    )
    passed = (
        response.status == "ok"
        and collaboration.get("enabled") is True
        and len(lanes) >= 3
        and bool(review.get("approved"))
        and not missing
        and test_run.returncode == 0
        and "collaboration.started" in event_types
        and "verification.completed" in event_types
        and not report["internal_protocol_exposed"]
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

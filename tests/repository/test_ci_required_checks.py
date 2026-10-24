"""The selected main protection contexts must be produced by ordinary PRs."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def _workflow(name):
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text())
    # PyYAML's YAML1.1 loader represents the workflow key `on` as True.
    events = workflow.get("on", workflow.get(True, {}))
    return workflow, events


def test_core_prs_produce_all_required_python_platform_contexts():
    workflow, events = _workflow("core-ci.yml")
    assert "main" in events["pull_request"]["branches"]
    matrix = workflow["jobs"]["python-tests"]["strategy"]["matrix"]["include"]
    assert isinstance(matrix, list), "PRs must not omit required platform jobs"
    assert {(row["os"], row["python"]) for row in matrix} == {
        ("ubuntu-22.04", "3.10"),
        ("ubuntu-22.04", "3.12"),
        ("windows-latest", "3.12"),
        ("macos-14", "3.12"),
    }
    assert workflow["jobs"]["core-gate"]["needs"] == ["python-tests"]


def test_multi_arch_required_contexts_run_actual_existing_jobs_on_prs():
    workflow, events = _workflow("multi-arch-build.yml")
    assert "main" in events.get("pull_request", {}).get("branches", []), (
        "Required multi-arch checks must be reachable from the PR event"
    )
    jobs = workflow["jobs"]
    for name in ("linux-amd64", "linux-arm64", "windows-amd64"):
        assert not jobs[name].get("if"), (
            "Required PR platform jobs cannot be gated away"
        )
        assert any("pytest" in str(step.get("run", "")) for step in jobs[name]["steps"])
    assert {"linux-amd64", "linux-arm64", "windows-amd64"}.issubset(
        set(jobs["sbom"]["needs"])
    )

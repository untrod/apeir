"""Verify an exact accepted native artifact and optionally stage an unpublished draft.

This extends Release Preflight. It never signs, publishes, creates a Git tag or
replaces assets. Windows installation and public release remain separate gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from scripts.ci.verify_kernel_components import admit_artifact


REPOSITORY = "untrod/apeir"


def _api(path: str, payload: dict[str, Any] | None = None) -> Any:
    argv = ["gh", "api", f"repos/{REPOSITORY}/{path}"]
    if payload is not None:
        argv += ["--method", "POST", "--input", "-"]
    result = subprocess.run(
        argv,
        input=json.dumps(payload) if payload is not None else None,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode:
        # Failed downloads may contain signed redirect URLs. Do not echo them.
        raise RuntimeError(
            "GitHub request failed; check the workflow identity and permissions"
        )
    return json.loads(result.stdout)


def validate_producer(
    producer: dict[str, Any],
    artifact: dict[str, Any],
    run_id: int,
    artifact_id: int,
    digest: str,
) -> str:
    revision = producer.get("head_sha", "")
    if (
        producer.get("id") != run_id
        or artifact.get("id") != artifact_id
        or producer.get("head_repository", {}).get("full_name") != REPOSITORY
        or producer.get("path") != ".github/workflows/desktop-build.yml"
        or producer.get("event") != "workflow_dispatch"
        or producer.get("status") != "completed"
        or producer.get("conclusion") != "success"
        or not re.fullmatch(r"[0-9a-f]{40}", revision)
        or artifact.get("workflow_run", {}).get("id") != run_id
        or artifact.get("workflow_run", {}).get("head_sha") != revision
        or artifact.get("name") != "windows-x64-native-development-build"
        or artifact.get("expired") is not False
        or type(artifact.get("size_in_bytes")) is not int
        or not 0 < artifact["size_in_bytes"] <= 256 * 1024 * 1024
        or artifact.get("digest", "").lower() != "sha256:" + digest.lower()
    ):
        raise ValueError("exact successful same-repository native artifact is required")
    return revision


def check_draft(draft: dict[str, Any], tag: str, revision: str) -> None:
    if (
        draft.get("draft") is not True
        or draft.get("prerelease") is not True
        or draft.get("tag_name") != tag
        or draft.get("target_commitish") != revision
    ):
        raise ValueError(
            "only the matching unpublished preview draft may receive assets"
        )


def check_existing_assets(draft: dict[str, Any], files: dict[str, Path]) -> set[str]:
    existing = set()
    for asset in draft.get("assets", []):
        name = asset.get("name")
        if name not in files or name in existing:
            raise ValueError(
                "draft has unexpected or duplicate assets; nothing will be replaced"
            )
        path = files[name]
        expected = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if (
            asset.get("digest", "").lower() != expected
            or asset.get("size") != path.stat().st_size
        ):
            raise ValueError(
                "draft asset bytes differ or cannot be verified; nothing will be replaced"
            )
        existing.add(name)
    return existing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--artifact-id", required=True, type=int)
    parser.add_argument("--zip-sha256", required=True)
    parser.add_argument("--workdir", required=True, type=Path)
    parser.add_argument("--stage-draft", action="store_true")
    args = parser.parse_args()
    if (
        os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
        or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or os.environ.get("GITHUB_REF") != "refs/heads/main"
    ):
        raise ValueError("manual protected-main Release Preflight is required")
    if (
        args.run_id <= 0
        or args.artifact_id <= 0
        or not re.fullmatch(r"[0-9A-Fa-f]{64}", args.zip_sha256)
    ):
        raise ValueError("exact reviewed run, artifact and SHA-256 are required")
    producer = _api(f"actions/runs/{args.run_id}")
    artifact = _api(f"actions/artifacts/{args.artifact_id}")
    revision = validate_producer(
        producer, artifact, args.run_id, args.artifact_id, args.zip_sha256
    )
    subprocess.run(["git", "merge-base", "--is-ancestor", revision, "HEAD"], check=True)
    # New task directory prevents stale files from contaminating a later attempt.
    args.workdir.mkdir(parents=True, exist_ok=False)
    archive = args.workdir / "reviewed-native.zip"
    with archive.open("xb") as stream:
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{REPOSITORY}/actions/artifacts/{args.artifact_id}/zip",
            ],
            stdout=stream,
            stderr=subprocess.PIPE,
            timeout=180,
        )
    if result.returncode:
        raise RuntimeError("exact native artifact download failed")
    package = args.workdir / "package"
    report = admit_artifact(
        archive,
        args.zip_sha256,
        package,
        Path("runtime-components.lock.json"),
        revision,
        artifact_format="native-build",
    )
    (args.workdir / "admission.json").write_text(json.dumps(report, indent=2) + "\n")
    if not args.stage_draft:
        print("PASS: exact native package verified; no release or tag changed")
        return 0
    version = json.loads(
        (package / "release-manifest.json").read_text(encoding="utf-8-sig")
    )["version"]
    tag = f"v{version}-windows-preview.{revision[:12]}"
    drafts = [
        item for item in _api("releases?per_page=100") if item.get("tag_name") == tag
    ]
    if len(drafts) > 1:
        raise ValueError("ambiguous preview draft")
    if drafts:
        draft = drafts[0]
    else:
        # A published historical tag is immutable, even without a visible release.
        ref = subprocess.run(
            ["git", "ls-remote", "--exit-code", "--tags", "origin", "refs/tags/" + tag],
            capture_output=True,
            timeout=60,
        )
        if ref.returncode != 2:
            raise ValueError("preview tag already exists or cannot be checked")
        draft = _api(
            "releases",
            {
                "tag_name": tag,
                "target_commitish": revision,
                "draft": True,
                "prerelease": True,
                "name": f"APEIR {version} Windows preview (unsigned draft)",
                "body": f"Unpublished preparation only. Source: `{revision}`. Native run: {args.run_id}; artifact: {args.artifact_id}.\n\nUnsigned Windows x64 development build. Actual component/build smoke was performed on Windows Server; Windows 10 GUI installation, upgrade/uninstall, Defender, signing and public release are not qualified. Do not publish before the Release Runbook and explicit maintainer approval.\n\nVerify SHA256SUMS.txt. No instruction to disable Windows security is provided.",
            },
        )
    check_draft(draft, tag, revision)
    files = {path.name: path for path in package.iterdir() if path.is_file()}
    existing = check_existing_assets(draft, files)
    for name, path in files.items():
        if name in existing:
            continue
        check_draft(_api(f"releases/{draft['id']}"), tag, revision)
        uploaded = subprocess.run(
            ["gh", "release", "upload", tag, str(path), "--repo", REPOSITORY],
            capture_output=True,
            timeout=180,
        )
        if uploaded.returncode:
            raise RuntimeError(
                "draft asset upload failed; retained draft is unpublished; no existing asset was replaced"
            )
    current = _api(f"releases/{draft['id']}")
    check_draft(current, tag, revision)
    if check_existing_assets(current, files) != set(files):
        raise ValueError("draft upload inventory is incomplete")
    (args.workdir / "draft-staging.json").write_text(
        json.dumps(
            {
                "draft_id": draft["id"],
                "source": revision,
                "tag_name": tag,
                "published": False,
                "assets": sorted(files),
                "installation_acceptance": "NOT_RUN",
            },
            indent=2,
        )
        + "\n"
    )
    print(
        "PASS: verified assets staged in an unpublished draft; publication gates remain pending"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import hashlib
import io
import json
import struct
import subprocess
import sys
import stat
import zipfile
from pathlib import Path

import pytest

from scripts.ci.verify_kernel_components import (
    admit_artifact,
    main,
    report_rebuild,
    verify,
)
from scripts.ci import stage_native_preview


def _write_pe(path: Path, machine: int = 0xAA64) -> None:
    data = bytearray(256)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 128)
    data[128:132] = b"PE\0\0"
    struct.pack_into("<H", data, 132, machine)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _write_lock(path: Path, artifact: Path, digest: str) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "components": {
                    "nous-kernel": {
                        "revision": "abc123",
                        "target": "aarch64-pc-windows-msvc",
                        "artifacts": [
                            {
                                "name": "nousd",
                                "path": artifact.as_posix(),
                                "sha256": digest,
                                "pe_machine": "0xAA64",
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def native_bundle(tmp_path):
    """Synthetic PE admission contracts, never native execution qualification."""
    binary = tmp_path / "fixture.exe"
    _write_pe(binary, machine=0x8664)
    content = binary.read_bytes()
    native_paths = [
        f"desktop/src-tauri/binaries/{name}-x86_64-pc-windows-msvc.exe"
        for name in ("nousd", "nous-provider-worker")
    ]
    lock = tmp_path / "lock.json"
    _write_lock(lock, Path(native_paths[0]), hashlib.sha256(content).hexdigest())
    document = json.loads(lock.read_text())
    component = document["components"]["nous-kernel"]
    component.update(target="x86_64-pc-windows-msvc", nki_versions=[1, 2, 3])
    component["artifacts"][0]["pe_machine"] = "0x8664"
    component["artifacts"].append(
        {
            **component["artifacts"][0],
            "name": "nous-provider-worker",
            "path": native_paths[1],
        }
    )
    lock.write_text(json.dumps(document))
    files = {path: content for path in native_paths + ["nous-runtime.exe"]}
    manifest = {
        "kernel_revision": "abc123",
        "distribution_revision": "1" * 40,
        "github_repository": "untrod/apeir",
        "source_build": "PASS",
        "native_smoke": "success",
        "files": [
            {"path": path, "sha256": hashlib.sha256(data).hexdigest()}
            for path, data in files.items()
        ],
    }
    smoke = {
        key: True
        for key in (
            "kernel_ready",
            "authenticated_status",
            "provider_worker_health",
            "invalid_nki_runtime_start_rejected",
            "invalid_http_sessions_rejected",
            "token_owner_only_dacl",
            "process_tree_closed",
            "kernel_process_tree_closed",
            "final_runtime_process_closed",
            "restarted_authenticated_status",
        )
    }
    smoke["target"] = "x86_64-pc-windows-msvc"
    nki = {
        "status": "PASS",
        "original_workload_id": "native-smoke-denied-model-" + "2" * 32,
        "original_profile_sha256": "3" * 64,
        "request_versions_exercised": [1, 2, 3],
    }
    recovery = {**nki, "recovery_query_only": True, "model_operation_submissions": 0}
    files.update(
        {
            name: json.dumps(value).encode()
            for name, value in {
                "candidate-manifest.json": manifest,
                "native-smoke.json": smoke,
                "nki-initial.json": nki,
                "nki-recovery.json": recovery,
            }.items()
        }
    )

    def bundle(fault=None):
        entries = dict(files)
        if fault == "path":
            entries["../escaped.exe"] = b"not admitted"
        elif fault == "missing-worker":
            entries.pop(native_paths[1])
        elif fault == "tamper-worker":
            entries[native_paths[1]] += b"changed"
        elif fault == "false-smoke":
            invalid = {**smoke, "token_owner_only_dacl": False}
            entries["native-smoke.json"] = json.dumps(invalid).encode()
        elif fault == "producer":
            entries["candidate-manifest.json"] = json.dumps(
                {**manifest, "distribution_revision": "4" * 40}
            ).encode()
        entries["SHA256SUMS.txt"] = "".join(
            f"{hashlib.sha256(data).hexdigest()}  {path}\n"
            for path, data in entries.items()
        ).encode()
        archive = tmp_path / "native.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            for path, data in entries.items():
                if fault == "symlink" and path == "nous-runtime.exe":
                    info = zipfile.ZipInfo(path)
                    info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    zipped.writestr(info, data)
                else:
                    zipped.writestr(path, data)
        if fault == "bomb":
            data = bytearray(archive.read_bytes())
            central = data.index(b"PK\x01\x02")
            struct.pack_into("<I", data, central + 24, 513 * 1024 * 1024)
            archive.write_bytes(data)
        return archive, hashlib.sha256(archive.read_bytes()).hexdigest()

    return lock, tmp_path / "admitted", bundle, files


def test_reviewed_archive_uses_real_lock_admission_and_does_not_replace_output(
    native_bundle,
):
    lock, output, bundle, files = native_bundle
    archive, digest = bundle()
    result = admit_artifact(archive, digest, output, lock, "1" * 40)
    assert result["status"] == "ok"
    assert result["installation_acceptance"] == "NOT_RUN"
    assert all((output / path).read_bytes() == data for path, data in files.items())
    with pytest.raises(ValueError, match="existing directory"):
        admit_artifact(archive, digest, output, lock, "1" * 40)
    assert all((output / path).read_bytes() == data for path, data in files.items())


@pytest.fixture
def full_native_bundle(native_bundle, tmp_path):
    """Synthetic package contracts; these bytes never qualify a native build."""
    lock, output, _, candidate_files = native_bundle
    version = "0.1.0-rc1"
    binaries = {}
    for name in ("nousd", "nous-provider-worker"):
        binaries["APEIR-Portable/" + name + ".exe"] = candidate_files[
            f"desktop/src-tauri/binaries/{name}-x86_64-pc-windows-msvc.exe"
        ]
    binaries["APEIR-Portable/nous-runtime.exe"] = candidate_files["nous-runtime.exe"]
    binaries["APEIR-Portable/APEIR.exe"] = candidate_files["nous-runtime.exe"]
    setup = tmp_path / "setup.exe"
    _write_pe(setup, machine=0x014C)
    smoke = json.loads(candidate_files["native-smoke.json"])
    nki = json.loads(candidate_files["nki-initial.json"])
    nki.update(
        wrong_and_missing_nki_credentials_rejected=True,
        invalid_versions_rejected=True,
        external_model_calls=0,
        model_operation_submissions=1,
        unauthorized_model_credential="DENIED_BEFORE_PROVIDER_SPAWN",
        original_failure_code="PROVIDER_ERROR",
    )
    recovery = json.loads(candidate_files["nki-recovery.json"])
    recovery["external_model_calls"] = 0
    smoke.update(nki=nki, restart_original_workload=recovery)
    smoke["version"] = version

    def bundle(fault=None):
        entries = dict(binaries)
        nested = io.BytesIO()
        with zipfile.ZipFile(nested, "w") as zipped:
            for name, data in binaries.items():
                zipped.writestr(
                    name, data + (b"tampered" if fault == "portable" else b"")
                )
        entries.update(
            {
                f"APEIR_{version}_x64-setup.exe": setup.read_bytes(),
                f"APEIR-Portable-{version}-windows-x64.zip": nested.getvalue(),
            }
        )
        manifest = {
            "schema_version": 1,
            "product": "APEIR",
            "version": version,
            "runtime_revision": "1" * 40,
            "kernel_revision": "abc123",
            "target": "x86_64-pc-windows-msvc",
            "sidecar_smoke_passed": True,
            "frontend_embedded": True,
            "runtime_sidecar": True,
            "source_state": {
                "runtime_worktree_dirty": False,
                "kernel_worktree_dirty": False,
            },
            "files": [
                {
                    "name": name,
                    "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
                for name, data in entries.items()
            ],
        }
        source = {
            "distribution_revision": "1" * 40,
            "kernel_revision": "abc123",
            "component_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
            "kernel_cargo_lock_sha256": hashlib.sha256(b"kernel-lock").hexdigest(),
            "desktop_cargo_lock_sha256": hashlib.sha256(b"desktop-lock").hexdigest(),
        }
        report = {
            "schema_version": 1,
            "status": "passed",
            "full_validation_executed": True,
            "target": "x86_64-pc-windows-msvc",
            "smoke": json.loads(json.dumps(smoke)),
        }
        if fault == "source":
            source["distribution_revision"] = "4" * 40
        elif fault == "lock":
            source["component_lock_sha256"] = "0" * 64
        elif fault == "cargo":
            source["kernel_cargo_lock_sha256"] = "0" * 64
        elif fault == "skipped":
            report["full_validation_executed"] = False
        elif fault == "cleanup":
            report["smoke"]["process_tree_closed"] = False
        elif fault == "auth":
            report["smoke"]["nki"]["wrong_and_missing_nki_credentials_rejected"] = False
        elif fault == "replay":
            report["smoke"]["restart_original_workload"][
                "model_operation_submissions"
            ] = 1
        elif fault == "identity":
            report["smoke"]["restart_original_workload"]["original_workload_id"] = (
                "other"
            )
        elif fault == "dirty":
            manifest["source_state"]["runtime_worktree_dirty"] = True
        entries.update(
            {
                name: json.dumps(value).encode()
                for name, value in {
                    "release-manifest.json": manifest,
                    f"APEIR-{version}-windows-x64.manifest.json": manifest,
                    "source-manifest.json": source,
                    "native-validation-report.json": report,
                }.items()
            }
        )
        entries.update(
            {
                "kernel-Cargo.lock": b"kernel-lock",
                "desktop-Cargo.lock": b"desktop-lock",
                "native-dependencies.json": b"{}",
                "platform-support.txt": b"contract fixture, not an installed product",
                "python-build-environment.cdx.json": b'{"bomFormat":"CycloneDX"}',
            }
        )
        if fault == "missing-sbom":
            entries.pop("python-build-environment.cdx.json")
        checksum = "".join(
            f"{hashlib.sha256(data).hexdigest()}  {name}\n"
            for name, data in entries.items()
        ).encode()
        entries.update({"SHA256SUMS.txt": checksum, "SHA256SUMS-x64.txt": checksum})
        if fault == "tamper":
            entries["APEIR-Portable/nousd.exe"] += b"changed"
        elif fault == "path":
            entries["../escape.exe"] = b"refused"
        elif fault == "coverage":
            entries["unlisted.json"] = b"{}"
        elif fault == "checksum-alias":
            entries["SHA256SUMS-x64.txt"] += b"changed"
        archive = tmp_path / "full-native.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            for name, data in entries.items():
                if fault == "symlink" and name == "APEIR-Portable/nousd.exe":
                    info = zipfile.ZipInfo(name)
                    info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    zipped.writestr(info, data)
                else:
                    zipped.writestr(name, data)
        return archive, hashlib.sha256(archive.read_bytes()).hexdigest()

    return lock, output, bundle


def test_qualified_native_build_reuses_unchanged_lock_and_original_bytes(
    full_native_bundle,
):
    lock, output, bundle = full_native_bundle
    original_lock = lock.read_bytes()
    archive, digest = bundle()
    result = admit_artifact(
        archive, digest, output, lock, "1" * 40, artifact_format="native-build"
    )
    assert result["status"] == "ok"
    assert result["installation_acceptance"] == "NOT_RUN"
    assert lock.read_bytes() == original_lock
    for item in result["artifacts"]:
        assert (output / item["path"]).read_bytes() == (
            output / "APEIR-Portable" / (item["name"] + ".exe")
        ).read_bytes()
    with pytest.raises(ValueError, match="existing directory"):
        admit_artifact(
            archive, digest, output, lock, "1" * 40, artifact_format="native-build"
        )


@pytest.mark.parametrize(
    "path",
    [
        "../escaped.exe",
        "C:/escaped.exe",
        "desktop\\escaped.exe",
        "/escaped.exe",
        "C:escaped.exe",
        "\\escaped.exe",
        "\\\\server\\share\\escaped.exe",
    ],
)
def test_native_build_refuses_unsafe_raw_lock_names(full_native_bundle, path):
    lock, output, bundle = full_native_bundle
    document = json.loads(lock.read_text())
    document["components"]["nous-kernel"]["artifacts"][0]["path"] = path
    lock.write_text(json.dumps(document))
    archive, digest = bundle()
    with pytest.raises(ValueError, match="unsafe locked component path"):
        admit_artifact(
            archive, digest, output, lock, "1" * 40, artifact_format="native-build"
        )
    assert not output.exists()


@pytest.mark.parametrize(
    "fault",
    [
        "source",
        "lock",
        "cargo",
        "missing-sbom",
        "skipped",
        "cleanup",
        "auth",
        "replay",
        "identity",
        "dirty",
        "portable",
        "tamper",
        "path",
        "coverage",
        "checksum-alias",
        "symlink",
    ],
)
def test_native_build_carrier_refuses_incomplete_or_tampered_inputs(
    full_native_bundle, fault
):
    lock, output, bundle = full_native_bundle
    archive, digest = bundle(fault)
    with pytest.raises(ValueError):
        admit_artifact(
            archive, digest, output, lock, "1" * 40, artifact_format="native-build"
        )
    assert not output.exists()


def _producer_and_artifact():
    return (
        {
            "id": 10,
            "head_sha": "1" * 40,
            "head_repository": {"full_name": "untrod/apeir"},
            "path": ".github/workflows/desktop-build.yml",
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
        },
        {
            "id": 20,
            "workflow_run": {"id": 10, "head_sha": "1" * 40},
            "name": "windows-x64-native-development-build",
            "expired": False,
            "size_in_bytes": 100,
            "digest": "sha256:" + "a" * 64,
        },
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("conclusion", "failure"),
        ("event", "pull_request"),
        ("head_sha", "invalid"),
        ("path", ".github/workflows/other.yml"),
        ("head_repository", {"full_name": "untrusted/fork"}),
    ],
)
def test_draft_staging_refuses_wrong_producer(field, value):
    producer, artifact = _producer_and_artifact()
    producer[field] = value
    with pytest.raises(ValueError):
        stage_native_preview.validate_producer(producer, artifact, 10, 20, "a" * 64)


@pytest.mark.parametrize(
    "field,value",
    [
        ("expired", True),
        ("digest", "sha256:" + "b" * 64),
        ("name", "unrelated.zip"),
        ("workflow_run", {"id": 11, "head_sha": "1" * 40}),
        ("size_in_bytes", 257 * 1024 * 1024),
    ],
)
def test_draft_staging_refuses_wrong_artifact(field, value):
    producer, artifact = _producer_and_artifact()
    artifact[field] = value
    with pytest.raises(ValueError):
        stage_native_preview.validate_producer(producer, artifact, 10, 20, "a" * 64)


@pytest.mark.parametrize(
    "field,value",
    [
        ("draft", False),
        ("prerelease", False),
        ("target_commitish", "other"),
        ("tag_name", "other"),
    ],
)
def test_staging_cannot_modify_published_or_unrelated_release(field, value):
    draft = {
        "draft": True,
        "prerelease": True,
        "target_commitish": "1" * 40,
        "tag_name": "tag",
    }
    draft[field] = value
    with pytest.raises(ValueError):
        stage_native_preview.check_draft(draft, "tag", "1" * 40)


def test_staging_refuses_unknown_or_changed_existing_assets(tmp_path):
    path = tmp_path / "artifact.zip"
    path.write_bytes(b"original")
    assets = [
        {
            "name": path.name,
            "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size,
        }
    ]
    assert stage_native_preview.check_existing_assets(
        {"assets": assets}, {path.name: path}
    ) == {path.name}
    with pytest.raises(ValueError):
        stage_native_preview.check_existing_assets({"assets": assets}, {})
    assets[0]["digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        stage_native_preview.check_existing_assets(
            {"assets": assets}, {path.name: path}
        )
    assert path.read_bytes() == b"original"


@pytest.mark.parametrize("stage", [False, True])
def test_preflight_uses_real_admission_and_only_stages_an_unpublished_draft(
    full_native_bundle, tmp_path, monkeypatch, stage
):
    lock, _, bundle = full_native_bundle
    archive, digest = bundle()
    monkeypatch.chdir(tmp_path)
    (tmp_path / "runtime-components.lock.json").write_bytes(lock.read_bytes())
    for key, value in {
        "GITHUB_REPOSITORY": "untrod/apeir",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
    }.items():
        monkeypatch.setenv(key, value)
    producer, artifact = _producer_and_artifact()
    artifact["digest"] = "sha256:" + digest
    task = tmp_path / "task"
    draft = {
        "id": 30,
        "draft": True,
        "prerelease": True,
        "target_commitish": "1" * 40,
        "tag_name": "v0.1.0-rc1-windows-preview." + "1" * 12,
        "assets": [],
    }
    created, uploaded = [], []

    def api(path, payload=None):
        if path == "actions/runs/10":
            return producer
        if path == "actions/artifacts/20":
            return artifact
        if path == "releases?per_page=100":
            return []
        if path == "releases":
            assert payload["draft"] is True and payload["prerelease"] is True
            assert payload["target_commitish"] == "1" * 40
            created.append(payload)
            return draft
        assert path == "releases/30"
        return draft

    def run(argv, **kwargs):
        if argv[:2] == ["git", "merge-base"]:
            return subprocess.CompletedProcess(argv, 0)
        if argv[:2] == ["git", "ls-remote"]:
            return subprocess.CompletedProcess(argv, 2)
        if argv[:2] == ["gh", "api"]:
            assert argv[-1].endswith("actions/artifacts/20/zip")
            kwargs["stdout"].write(archive.read_bytes())
            return subprocess.CompletedProcess(argv, 0)
        assert argv[:3] == ["gh", "release", "upload"]
        assert "--clobber" not in argv
        path = Path(argv[4])
        uploaded.append(path.name)
        draft["assets"].append(
            {
                "name": path.name,
                "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": path.stat().st_size,
            }
        )
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(stage_native_preview, "_api", api)
    monkeypatch.setattr(stage_native_preview.subprocess, "run", run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "preflight",
            "--run-id",
            "10",
            "--artifact-id",
            "20",
            "--zip-sha256",
            digest,
            "--workdir",
            str(task),
        ]
        + (["--stage-draft"] if stage else []),
    )
    assert stage_native_preview.main() == 0
    assert json.loads((task / "admission.json").read_text())["status"] == "ok"
    assert bool(created) is stage
    assert bool(uploaded) is stage
    if stage:
        assert (
            json.loads((task / "draft-staging.json").read_text())["published"] is False
        )
    else:
        assert not (task / "draft-staging.json").exists()


def test_release_preflight_retains_manual_main_and_publication_boundary():
    import yaml

    path = Path(__file__).parents[2] / ".github/workflows/release.yml"
    workflow = yaml.safe_load(path.read_text())
    events = workflow.get("on", workflow.get(True))
    assert set(events) == {"workflow_dispatch"}
    assert events["workflow_dispatch"]["inputs"]["stage_draft"]["default"] is False
    assert workflow["permissions"] == {"contents": "read", "actions": "read"}
    staging = workflow["jobs"]["stage-unpublished-draft"]
    assert staging["needs"] == "native-integrity"
    assert "github.ref == 'refs/heads/main'" in staging["if"]
    assert "inputs.stage_draft == true" in staging["if"]
    assert staging["permissions"] == {"contents": "write", "actions": "read"}
    assert "persist-credentials: false" in path.read_text()
    assert "--draft=false" not in path.read_text()


def test_preflight_rejects_non_main_before_github_or_disk_changes(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GITHUB_REPOSITORY", "untrod/apeir")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/untrusted")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "preflight",
            "--run-id",
            "10",
            "--artifact-id",
            "20",
            "--zip-sha256",
            "a" * 64,
            "--workdir",
            str(tmp_path / "task"),
        ],
    )
    with pytest.raises(ValueError, match="protected-main"):
        stage_native_preview.main()
    assert not (tmp_path / "task").exists()


@pytest.mark.parametrize(
    "fault",
    [
        "path",
        "symlink",
        "bomb",
        "missing-worker",
        "tamper-worker",
        "false-smoke",
        "producer",
        "outer-sha",
    ],
)
def test_bad_archive_never_publishes_any_native_input(native_bundle, fault):
    lock, output, bundle, _ = native_bundle
    original_lock = lock.read_bytes()
    archive, digest = bundle(fault)
    with pytest.raises((ValueError, FileNotFoundError)):
        admit_artifact(
            archive,
            "0" * 64 if fault == "outer-sha" else digest,
            output,
            lock,
            "1" * 40,
        )
    assert not output.exists()
    assert lock.read_bytes() == original_lock
    assert not list(output.parent.glob("native-admission-*"))


def test_smoke_manifest_cannot_approve_hashes_outside_component_lock(native_bundle):
    lock, output, bundle, _ = native_bundle
    archive, digest = bundle()
    document = json.loads(lock.read_text())
    document["components"]["nous-kernel"]["artifacts"][0]["sha256"] = "0" * 64
    lock.write_text(json.dumps(document))
    original = lock.read_bytes()
    with pytest.raises(ValueError, match="hash mismatch"):
        admit_artifact(archive, digest, output, lock, "1" * 40)
    assert lock.read_bytes() == original and not output.exists()


def test_component_lock_verifies_hash_and_architecture(tmp_path: Path) -> None:
    relative = Path("desktop/bin/nousd.exe")
    artifact = tmp_path / relative
    _write_pe(artifact)
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    lock = tmp_path / "runtime-components.lock.json"
    _write_lock(lock, relative, digest)

    result = verify(tmp_path, lock, None)

    assert result[0]["name"] == "nousd"
    assert result[0]["pe_machine"] == "0xAA64"


def test_component_lock_rejects_modified_binary(tmp_path: Path) -> None:
    relative = Path("desktop/bin/nousd.exe")
    artifact = tmp_path / relative
    _write_pe(artifact)
    lock = tmp_path / "runtime-components.lock.json"
    _write_lock(lock, relative, "0" * 64)

    with pytest.raises(ValueError, match="hash mismatch"):
        verify(tmp_path, lock, None)


def test_component_lock_rejects_path_escape(tmp_path: Path) -> None:
    lock = tmp_path / "runtime-components.lock.json"
    _write_lock(lock, Path("../nousd.exe"), "0" * 64)

    with pytest.raises(ValueError, match="unsafe component path"):
        verify(tmp_path, lock, None)


@pytest.mark.parametrize(
    ("target", "expected_machine"),
    [
        ("x86_64-pc-windows-msvc", "0x8664"),
        ("aarch64-pc-windows-msvc", "0xAA64"),
    ],
)
def test_locked_64bit_component_rejects_32bit_pe_with_matching_hash(
    tmp_path: Path, target: str, expected_machine: str
) -> None:
    relative = Path("desktop/bin/nousd.exe")
    artifact = tmp_path / relative
    _write_pe(artifact, machine=0x014C)
    original = artifact.read_bytes()
    lock = tmp_path / "runtime-components.lock.json"
    _write_lock(lock, relative, hashlib.sha256(original).hexdigest())
    data = json.loads(lock.read_text())
    data["components"]["nous-kernel"]["target"] = target
    data["components"]["nous-kernel"]["artifacts"][0]["pe_machine"] = expected_machine
    lock.write_text(json.dumps(data), encoding="utf-8")
    original_lock = lock.read_bytes()

    # Digest admission succeeds, so rejection must come from the real PE
    # architecture boundary, not an unrelated missing file or hash mismatch.
    with pytest.raises(ValueError, match="architecture mismatch"):
        verify(tmp_path, lock, None)

    assert artifact.read_bytes() == original
    assert lock.read_bytes() == original_lock


@pytest.fixture
def rebuilt_candidate(tmp_path: Path) -> tuple[Path, Path, Path]:
    kernel = tmp_path / "kernel"
    kernel.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=kernel, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Contract Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "fixture",
        ],
        cwd=kernel,
        check=True,
    )
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=kernel, text=True
    ).strip()
    candidates = kernel / "target" / "release"
    artifact = candidates / "nousd.exe"
    _write_pe(artifact)
    lock = tmp_path / "runtime-components.lock.json"
    _write_lock(
        lock,
        Path("desktop/bin/nousd.exe"),
        hashlib.sha256(artifact.read_bytes()).hexdigest(),
    )
    data = json.loads(lock.read_text())
    data["components"]["nous-kernel"]["revision"] = revision
    # Both locked components must be inspected, even when the first is invalid.
    second = dict(data["components"]["nous-kernel"]["artifacts"][0])
    second.update(name="nous-provider-worker", path="desktop/bin/worker.exe")
    data["components"]["nous-kernel"]["artifacts"].append(second)
    _write_pe(candidates / "nous-provider-worker.exe")
    lock.write_text(json.dumps(data), encoding="utf-8")
    return lock, kernel, candidates


def test_rebuild_report_requires_both_actual_hashes_and_architectures(
    rebuilt_candidate,
) -> None:
    lock, kernel, candidates = rebuilt_candidate
    report = report_rebuild(lock, kernel, candidates)
    assert report["status"] == "MATCH"
    assert report["tracked_source_clean"] is True
    assert report["installation_acceptance"] == "NOT_RUN"
    assert report["runtime_nki_validation"] == "NOT_RUN"
    assert len(report["artifacts"]) == 2
    assert all(
        item["sha256"] == item["expected_sha256"] for item in report["artifacts"]
    )
    assert all(item["pe_machine"] == "0xAA64" for item in report["artifacts"])


@pytest.mark.parametrize(
    "fault", ["hash", "architecture", "invalid_pe", "missing", "revision", "source"]
)
def test_rebuild_report_fails_closed_and_keeps_original_lock(
    rebuilt_candidate, fault
) -> None:
    lock, kernel, candidates = rebuilt_candidate
    original_lock = lock.read_bytes()
    path = candidates / "nousd.exe"
    if fault == "hash":
        path.write_bytes(path.read_bytes() + b"modified")
    elif fault == "architecture":
        data = bytearray(path.read_bytes())
        struct.pack_into("<H", data, 132, 0x8664)
        path.write_bytes(data)
    elif fault == "invalid_pe":
        path.write_bytes(b"not a Windows executable")
    elif fault == "missing":
        path.unlink()
    elif fault == "revision":
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "--allow-empty",
                "-qm",
                "another revision",
            ],
            cwd=kernel,
            check=True,
        )
    else:
        tracked = kernel / "source.txt"
        tracked.write_text("original", encoding="utf-8")
        subprocess.run(["git", "add", "source.txt"], cwd=kernel, check=True)
    report = report_rebuild(lock, kernel, candidates)
    assert report["status"] == "BLOCKED"
    assert report["errors"]
    assert len(report["artifacts"]) == 2
    assert report["artifacts"][1]["errors"] == []
    assert lock.read_bytes() == original_lock


def test_rebuild_cli_writes_blocked_evidence_and_returns_nonzero(
    rebuilt_candidate, monkeypatch, tmp_path
) -> None:
    lock, kernel, candidates = rebuilt_candidate
    (candidates / "nousd.exe").unlink()
    output = tmp_path / "evidence" / "report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify",
            "--lock",
            str(lock),
            "--kernel-root",
            str(kernel),
            "--candidate-root",
            str(candidates),
            "--report",
            str(output),
        ],
    )
    assert main() == 2
    assert json.loads(output.read_text())["status"] == "BLOCKED"
    assert not (tmp_path / "desktop").exists()


def test_rebuild_cli_cannot_overwrite_component_lock(
    rebuilt_candidate, monkeypatch
) -> None:
    lock, kernel, candidates = rebuilt_candidate
    original = lock.read_bytes()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify",
            "--lock",
            str(lock),
            "--kernel-root",
            str(kernel),
            "--candidate-root",
            str(candidates),
            "--report",
            str(lock),
        ],
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert lock.read_bytes() == original


def test_new_arm64_bytes_never_satisfy_the_maintained_x64_lock(
    rebuilt_candidate, tmp_path
) -> None:
    lock, kernel, candidates = rebuilt_candidate
    document = json.loads(lock.read_text())
    component = document["components"]["nous-kernel"]
    component["target"] = "x86_64-pc-windows-msvc"
    package = tmp_path / "package"
    for artifact in component["artifacts"]:
        # Even a matching digest cannot approve a different PE architecture.
        artifact["pe_machine"] = "0x8664"
        target = package / artifact["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((candidates / (artifact["name"] + ".exe")).read_bytes())
    lock.write_text(json.dumps(document))
    before = lock.read_bytes()
    report = report_rebuild(lock, kernel, candidates)
    assert report["status"] == "BLOCKED"
    assert all(item["pe_machine"] == "0xAA64" for item in report["artifacts"])
    assert all(
        item["errors"] == ["architecture mismatch"] for item in report["artifacts"]
    )
    with pytest.raises(ValueError, match="architecture mismatch"):
        verify(package, lock, kernel)
    assert lock.read_bytes() == before

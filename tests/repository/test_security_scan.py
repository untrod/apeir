from pathlib import Path

from scripts import security_scan


def _scan_text(
    tmp_path: Path,
    monkeypatch,
    relative_path: str,
    content: str,
) -> list[dict]:
    monkeypatch.setattr(security_scan, "REPO_ROOT", tmp_path)
    target = tmp_path / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return security_scan.scan_file(target)


def test_credential_findings_are_redacted(tmp_path: Path, monkeypatch) -> None:
    secret = "sk-" + "x" * 32  # security-scan: fixture
    findings = _scan_text(tmp_path, monkeypatch, "src/config.py", secret)

    assert findings
    assert all(finding["content"] == "[redacted]" for finding in findings)
    assert secret not in security_scan.format_finding(findings[0])


def test_absolute_paths_are_allowed_as_test_fixtures(
    tmp_path: Path,
    monkeypatch,
) -> None:
    findings = _scan_text(
        tmp_path,
        monkeypatch,
        "desktop/src/test/migration.test.ts",
        'const legacy = "D:\\\\Agent_play\\\\workspace";',
    )

    assert not any(finding["pattern"].startswith("Windows absolute path") for finding in findings)


def test_native_object_files_are_excluded() -> None:
    assert security_scan._is_excluded("build/nous_micro.obj")



def test_explicit_test_fixture_marker_is_scoped(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fixture = 'value = "sk-abcdefghijklmnopqrstuvwxyz123456"  # security-scan: fixture'
    assert _scan_text(tmp_path, monkeypatch, "tests/test_fixture.py", fixture) == []

    findings = _scan_text(tmp_path, monkeypatch, "src/config.py", fixture)
    assert any(finding["severity"] == "HIGH" for finding in findings)


def test_generated_artifacts_are_excluded() -> None:
    assert security_scan._is_excluded("artifacts/build-env/site-packages/vendor.py")

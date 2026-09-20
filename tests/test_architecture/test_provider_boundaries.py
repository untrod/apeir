from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

PUBLIC_PROVIDER_SURFACES = [
    "nous_runtime/api/routes.py",
    "nous_runtime/cli/doctor.py",
    "nous_runtime/cli/shell.py",
    "nous_runtime/cli/shell_v2.py",
    "nous_runtime/sdk/client.py",
]


def test_public_provider_surfaces_use_provider_service():
    findings: list[str] = []
    for rel_name in PUBLIC_PROVIDER_SURFACES:
        path = REPO_ROOT / rel_name
        text = path.read_text(encoding="utf-8", errors="replace")
        if "nous_runtime.provider.registry" in text:
            findings.append(rel_name)

    assert findings == []
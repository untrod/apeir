from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

PUBLIC_SURFACE_FILES = [
    "nous_runtime/api/routes.py",
    "nous_runtime/cli/dev_commands.py",
    "nous_runtime/cli/doctor.py",
    "nous_runtime/cli/main.py",
    "nous_runtime/cli/provider_setup.py",
    "nous_runtime/cli/shell.py",
    "nous_runtime/cli/shell_v2.py",
    "nous_runtime/sdk/client.py",
    "nous_runtime/sdk/advanced.py",
]


def test_public_surfaces_do_not_import_compat_directly():
    findings: list[str] = []
    for rel_name in PUBLIC_SURFACE_FILES:
        path = REPO_ROOT / rel_name
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if "nous_runtime.compat" in line and (" import " in line or line.lstrip().startswith("import ")):
                findings.append(f"{rel_name}:{lineno}: {line.strip()}")

    assert findings == []

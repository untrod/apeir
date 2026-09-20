from pathlib import Path

from nous_runtime.state.ownership import STATE_OWNERSHIP, validate_unique_state_owners


REPO_ROOT = Path(__file__).resolve().parents[2]

PUBLIC_SURFACE_FILES = [
    "nous_runtime/api/routes.py",
    "nous_runtime/cli/main.py",
    "nous_runtime/cli/provider_setup.py",
    "nous_runtime/cli/shell.py",
    "nous_runtime/cli/shell_v2.py",
    "nous_runtime/cli/wizard.py",
    "nous_runtime/sdk/client.py",
]

FORBIDDEN_PUBLIC_IMPORTS = (
    "from nous_runtime.pack.registry import registry",
    "from nous_runtime.compat.db import run_migrations",
)


def test_state_ownership_registry_has_unique_states():
    assert validate_unique_state_owners() == []
    assert len({record.state for record in STATE_OWNERSHIP}) == len(STATE_OWNERSHIP)


def test_public_surfaces_use_state_services_for_owned_state():
    findings: list[str] = []
    for rel_name in PUBLIC_SURFACE_FILES:
        path = REPO_ROOT / rel_name
        text = path.read_text(encoding="utf-8", errors="replace")
        for forbidden in FORBIDDEN_PUBLIC_IMPORTS:
            if forbidden in text:
                findings.append(f"{rel_name}: {forbidden}")

    assert findings == []

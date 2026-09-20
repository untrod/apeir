from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_distribution_runtime_owns_only_user_space_lifecycle():
    path = REPO_ROOT / "nous_runtime" / "runtime" / "lifecycle.py"
    text = path.read_text(encoding="utf-8", errors="replace")

    assert "nous_runtime.services.lifecycle" in text
    assert "compat.nki_client" not in text
    assert "permit" not in text.split('"""', 2)[-1]
    assert "journal" not in text.split('"""', 2)[-1]


def test_old_kernel_runtime_is_only_a_compatibility_shim():
    path = REPO_ROOT / "nous_runtime" / "kernel" / "runtime.py"
    text = path.read_text(encoding="utf-8", errors="replace")

    assert "from nous_runtime.runtime.lifecycle import" in text
    assert "class Runtime" not in text
    assert "def start(" not in text


def test_product_code_does_not_import_the_old_runtime_authority():
    permitted = {
        REPO_ROOT / "nous_runtime" / "kernel" / "server.py",
    }
    offenders = []
    for path in (REPO_ROOT / "nous_runtime").rglob("*.py"):
        if path in permitted:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "from nous_runtime.kernel.runtime import" in text:
            offenders.append(path.relative_to(REPO_ROOT).as_posix())
    assert offenders == []

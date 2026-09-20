import json

from nous_runtime.deployment.product_installer import (
    InstallMode,
    ProductInstaller,
)


def test_product_installer_plans_all_modes(tmp_path):
    installer = ProductInstaller(tmp_path / "Nous")
    assert "desktop" in installer.plan(InstallMode.RECOMMENDED).components
    assert "developer_tools" in installer.plan(InstallMode.DEVELOPER).components
    assert "desktop" not in installer.plan(InstallMode.RUNTIME_ONLY).components
    assert installer.plan(InstallMode.PORTABLE).mode is InstallMode.PORTABLE


def test_product_installer_applies_reversible_layout(tmp_path):
    root = tmp_path / "Nous"
    installer = ProductInstaller(root)
    plan = installer.apply(InstallMode.RECOMMENDED)
    manifest = json.loads(
        (root / "config" / "installation.json").read_text(encoding="utf-8")
    )
    assert plan.install_root == str(root.resolve())
    assert manifest["mode"] == "recommended"
    assert (root / "bin" / "Nous.cmd").is_file()
    assert (root / "models").is_dir()


def test_product_installer_dry_run_does_not_write(tmp_path):
    root = tmp_path / "Nous"
    ProductInstaller(root).apply(dry_run=True)
    assert not root.exists()

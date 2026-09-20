from typer.testing import CliRunner

from nous_runtime.cli.main import app


runner = CliRunner()


def test_product_install_plan_is_non_mutating(tmp_path):
    root = tmp_path / "Nous"
    result = runner.invoke(
        app,
        [
            "install",
            "plan",
            "--path",
            str(root),
            "--mode",
            "runtime_only",
        ],
    )
    assert result.exit_code == 0
    assert '"mode": "runtime_only"' in result.output
    assert not root.exists()


def test_product_install_apply_requires_explicit_confirmation(tmp_path):
    root = tmp_path / "Nous"
    result = runner.invoke(
        app,
        [
            "install",
            "apply",
            "--path",
            str(root),
            "--mode",
            "portable",
            "--yes",
        ],
    )
    assert result.exit_code == 0
    assert (root / "config" / "installation.json").is_file()

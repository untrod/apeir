"""An editable checkout must not certify independent wheel installation."""

import pytest

from scripts.ci.verify_source_preview_install import qualify


def test_source_qualification_refuses_checkout_before_starting_a_process(
    monkeypatch, tmp_path
):
    import nous_runtime

    monkeypatch.setattr(nous_runtime, "__file__", str(tmp_path / "nous_runtime.py"))
    monkeypatch.setattr(
        "scripts.ci.verify_source_preview_install.subprocess.run",
        lambda *args, **kwargs: pytest.fail("checkout launched qualification process"),
    )
    with pytest.raises(RuntimeError, match="checkout imports"):
        qualify()

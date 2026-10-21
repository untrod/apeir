"""Reject ambiguous user spelling before Windows path normalization."""

import os
from types import SimpleNamespace

import pytest

from nous_runtime.security import private_files


@pytest.mark.parametrize(
    "name", ["policy.json.", "policy.json ", "policy.json:stream", "POLICY~1.JSON"]
)
def test_windows_policy_name_rejected_before_abspath(name, monkeypatch):
    def normalize(_):
        pytest.fail("ambiguous owner policy reached path normalization")

    monkeypatch.setattr(
        private_files,
        "os",
        SimpleNamespace(
            name="nt", fspath=os.fspath, path=SimpleNamespace(abspath=normalize)
        ),
    )
    with pytest.raises(PermissionError):
        private_files.read_current_user_only_windows_file(
            name, max_bytes=65536, subject="Owner permission policy"
        )

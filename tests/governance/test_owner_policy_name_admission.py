"""Reject ambiguous user spelling before Windows path normalization."""

import os
from types import SimpleNamespace

import pytest

from nous_runtime.security import private_files
from nous_runtime.governance import gate


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


@pytest.mark.parametrize(
    "name", ["policy.json.", "policy.json ", "policy.json:stream", "POLICY~1.JSON"]
)
def test_host_policy_spelling_is_checked_before_absolute_path(name, monkeypatch):
    monkeypatch.setenv("NOUS_PERMISSION_POLICY", name)
    monkeypatch.setattr(gate, "os", SimpleNamespace(name="nt", environ=os.environ))
    monkeypatch.setattr(
        gate.Path,
        "absolute",
        lambda *_: pytest.fail("host policy normalized before admission"),
    )
    store = SimpleNamespace(db_path="unused-private-state")
    with pytest.raises(PermissionError):
        gate.ExecutionAuthorizationGate(store=store)

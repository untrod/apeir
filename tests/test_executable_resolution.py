from nous_runtime.execution import executables


def test_windows_alias_uses_real_interpreter(tmp_path, monkeypatch):
    alias = tmp_path / "WindowsApps" / "python.exe"
    actual = tmp_path / "runtime" / "python.exe"
    actual.parent.mkdir()
    actual.touch()
    monkeypatch.setattr(executables.shutil, "which", lambda _: str(alias))
    monkeypatch.setattr(executables.sys, "executable", str(actual))
    monkeypatch.setattr(executables.sys, "frozen", False, raising=False)
    assert executables.resolve_executable("python") == str(actual.resolve())
    assert executables.resolve_executable(str(alias)) == str(alias)


def test_frozen_sidecar_is_not_used_as_python(tmp_path, monkeypatch):
    alias = str(tmp_path / "WindowsApps" / "python.exe")
    monkeypatch.setattr(executables.shutil, "which", lambda _: alias)
    monkeypatch.setattr(executables.sys, "frozen", True, raising=False)
    assert executables.resolve_executable("python") == alias


def test_native_path_interpreter_is_preserved(tmp_path, monkeypatch):
    interpreter = str(tmp_path / "venv" / "python.exe")
    monkeypatch.setattr(executables.shutil, "which", lambda _: interpreter)
    assert executables.resolve_executable("python") == interpreter

from __future__ import annotations


import pytest

from nous_runtime.capability.sandbox import SandboxResult
from nous_runtime.events import EventStream
from nous_runtime.workspace.workbench import DeveloperWorkbench, WorkbenchConflict, WorkbenchError


def test_workbench_lists_reads_and_searches_utf8_files(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "hello.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("secret", encoding="utf-8")
    workbench = DeveloperWorkbench(tmp_path)

    listing = workbench.list_files()
    read = workbench.read_file("src/hello.py")
    search = workbench.search("HELLO")

    assert [item["path"] for item in listing["files"]] == ["src/hello.py"]
    assert read["content"].splitlines() == ["print('hello')"]
    assert read["sha256"]
    assert search["matches"][0]["line"] == 1


def test_workbench_preview_atomic_write_backup_and_event_ledger(tmp_path):
    target = tmp_path / "main.py"
    target.write_text("print('before')\n", encoding="utf-8")
    workbench = DeveloperWorkbench(tmp_path)
    original = workbench.read_file("main.py")

    preview = workbench.preview_write(
        "main.py",
        "print('after')\n",
        expected_sha256=original["sha256"],
    )
    written = workbench.write_file(
        "main.py",
        "print('after')\n",
        expected_sha256=original["sha256"],
    )

    assert preview["changed"] is True
    assert "-print('before')" in preview["diff"]
    assert "+print('after')" in preview["diff"]
    assert target.read_text(encoding="utf-8") == "print('after')\n"
    assert (tmp_path / written["backup_path"]).read_text(encoding="utf-8") == "print('before')\n"
    events = EventStream(str(tmp_path)).load_events(written["run_id"])
    assert [event.event_type for event in events] == [
        "run.created",
        "command.proposed",
        "run.started",
        "file.changed",
        "run.completed",
    ]
    assert events[3].payload["after_sha256"] == written["after_sha256"]


def test_workbench_compare_and_swap_rejects_stale_and_escaped_paths(tmp_path):
    target = tmp_path / "main.py"
    target.write_text("before", encoding="utf-8")
    workbench = DeveloperWorkbench(tmp_path)
    stale_hash = workbench.read_file("main.py")["sha256"]
    target.write_text("changed elsewhere", encoding="utf-8")

    with pytest.raises(WorkbenchConflict):
        workbench.write_file("main.py", "replacement", expected_sha256=stale_hash)
    with pytest.raises(WorkbenchError):
        workbench.read_file("../outside.txt")
    with pytest.raises(WorkbenchError):
        workbench.write_file(".git/config", "bad")


def test_workbench_runs_only_fixed_profiles_through_strict_sandbox(tmp_path, monkeypatch):
    script = tmp_path / "hello.py"
    script.write_text("print('hello')\n", encoding="utf-8")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SandboxResult(ok=True, stdout="hello\n", returncode=0, runtime_seconds=0.01)

    monkeypatch.setattr("nous_runtime.workspace.workbench.run_process_strict", fake_run)
    workbench = DeveloperWorkbench(tmp_path)
    result = workbench.run_profile("python", target="hello.py")

    assert result["ok"] is True
    assert result["stdout"] == "hello\n"
    assert calls[0][0][1:] == ["hello.py"]
    assert calls[0][1]["cwd"] == str(tmp_path.resolve())
    events = EventStream(str(tmp_path)).load_events(result["run_id"])
    assert "command.output" in [event.event_type for event in events]
    assert events[-1].event_type == "run.completed"
    with pytest.raises(WorkbenchError):
        workbench.run_profile("powershell", target="hello.py")

def test_packaged_runtime_resolves_real_python_instead_of_sidecar(tmp_path, monkeypatch):
    import nous_runtime.workspace.workbench as module

    monkeypatch.setattr(module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        module.shutil,
        "which",
        lambda name: "C:/Python/python.exe" if name == "python" else None,
    )

    profiles = {item["name"]: item for item in DeveloperWorkbench.profiles()}

    assert profiles["python"]["available"] is True
    assert profiles["python"]["executable"] == "C:/Python/python.exe"
    assert profiles["python"]["executable"] != module.sys.executable
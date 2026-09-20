"""Native host-boundary gate; these are not mocked capability checks."""

import json
import os
import sys
from pathlib import Path

import pytest

from nous_runtime.kernel.sandbox import SandboxPolicy
from nous_runtime.kernel.windows_sandbox import executable_path, run


@pytest.mark.skipif(sys.platform != "win32" or executable_path() is None,
                    reason="Windows Sandbox is unavailable")
def test_real_vm_filesystem_network_and_environment_boundaries(tmp_path, monkeypatch):
    workspace = tmp_path / "work"
    readonly = tmp_path / "readonly"
    outside = tmp_path / "outside"
    for path in (workspace, readonly, outside):
        path.mkdir()
    secret = outside / "host-only.txt"
    secret.write_text("host-only-value", encoding="utf-8")
    monkeypatch.setenv("UNRELATED_HOST_SECRET", "do-not-inherit")
    # Read-only mapping is Path3: Control, Workspace, read scope, write scope
    # are resolved using the same explicit path translation as production.
    from nous_runtime.kernel.windows_sandbox import _build_mappings

    shell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    policy = SandboxPolicy(
        executable=str(shell), working_dir=str(workspace),
        read_allowed_paths=[str(readonly)], write_allowed_paths=[str(workspace)],
        timeout_seconds=20, max_memory_bytes=2048 * 1024 * 1024,
    )
    control = tmp_path / "probe-control"
    control.mkdir()
    mappings, _ = _build_mappings(policy, control)
    ro_guest = next(guest for host, guest, _ in mappings if host == readonly)
    quoted_secret = str(secret).replace("'", "''")
    command = f"""
$ErrorActionPreference = 'Stop'
$r = @{{}}
[IO.File]::WriteAllText((Join-Path (Get-Location) 'written.txt'), 'inside')
try {{ [IO.File]::WriteAllText('{ro_guest}\\forbidden.txt', 'bad'); $r.readonly_blocked=$false }}
catch {{ $r.readonly_blocked=$true }}
$r.outside_blocked = -not (Test-Path -LiteralPath '{quoted_secret}')
$r.environment_blocked = -not [bool]$env:UNRELATED_HOST_SECRET
$client = New-Object Net.Sockets.TcpClient
try {{ $a=$client.BeginConnect('1.1.1.1',443,$null,$null); $r.network_blocked=-not $a.AsyncWaitHandle.WaitOne(2000); if (-not $r.network_blocked) {{ $client.EndConnect($a); $r.network_blocked=-not $client.Connected }} }}
catch {{ $r.network_blocked=$true }} finally {{ $client.Close() }}
$r | ConvertTo-Json -Compress
"""
    policy.args = ["-NoProfile", "-NonInteractive", "-Command", command]
    result = run(policy)
    assert result.exit_code == 0, result.stderr
    evidence = json.loads(result.stdout)
    assert evidence == dict(readonly_blocked=True, outside_blocked=True,
                            environment_blocked=True, network_blocked=True)
    assert (workspace / "written.txt").read_text() == "inside"
    assert not (readonly / "forbidden.txt").exists()
    assert secret.read_text() == "host-only-value"


@pytest.mark.skipif(sys.platform != "win32" or executable_path() is None,
                    reason="Windows Sandbox is unavailable")
def test_real_vm_preserves_binary_stdin(tmp_path):
    import base64
    shell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    command = (
        "$m=New-Object IO.MemoryStream; "
        "[Console]::OpenStandardInput().CopyTo($m); "
        "[Console]::Write([Convert]::ToBase64String($m.ToArray()))"
    )
    policy = SandboxPolicy(
        executable=str(shell),
        args=["-NoProfile", "-NonInteractive", "-Command", command],
        working_dir=str(tmp_path), timeout_seconds=5,
    )
    data = bytes(range(256))
    result = run(policy, data)
    assert result.exit_code == 0, result.stderr
    assert base64.b64decode(result.stdout) == data


@pytest.mark.skipif(sys.platform != "win32" or executable_path() is None,
                    reason="Windows Sandbox is unavailable")
@pytest.mark.parametrize("mode", ["output", "timeout"])
def test_real_vm_output_budget_and_timeout(tmp_path, mode):
    shell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    command = (
        "[Console]::Out.Write(('x' * 1000000)); [Console]::Error.Write(('y' * 1000000))"
        if mode == "output" else "Start-Sleep -Seconds 120"
    )
    policy = SandboxPolicy(
        executable=str(shell),
        args=["-NoProfile", "-NonInteractive", "-Command", command],
        working_dir=str(tmp_path), read_allowed_paths=[str(tmp_path)],
        timeout_seconds=5, max_output_bytes=4096,
    )
    result = run(policy)
    if mode == "output":
        assert result.exit_code == 0, result.stderr
        assert result.output_truncated
        assert 0 < len(result.stdout.encode()) + len(result.stderr.encode()) <= 4096
    else:
        assert result.timed_out, result
        assert result.exit_code != 0


@pytest.mark.skipif(sys.platform != "win32" or executable_path() is None,
                    reason="Windows Sandbox is unavailable")
@pytest.mark.parametrize("resource", ["processes", "memory", "cpu"])
def test_real_vm_job_object_resource_limits(tmp_path, resource):
    shell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    if resource == "processes":
        command = (
            "$ErrorActionPreference='Stop'; "
            "try { $p=Start-Process powershell.exe -ArgumentList '-NoProfile','-Command','Start-Sleep 30' -PassThru; "
            "Start-Sleep -Milliseconds 500; if (-not $p.HasExited) { 'spawned'; exit 9 }; 'blocked' } "
            "catch { 'blocked' }"
        )
        memory = 256 * 1024 * 1024
        cpu = 10
        processes = 1
    elif resource == "memory":
        command = (
            "$x = New-Object byte[] (256MB); "
            "for($i=0; $i -lt $x.Length; $i+=4096) { $x[$i]=1 }; "
            "Start-Sleep -Seconds 10; 'allocated'"
        )
        memory = 64 * 1024 * 1024
        cpu = 10
        processes = 2
    else:
        command = "$until=[DateTime]::UtcNow.AddSeconds(20); while([DateTime]::UtcNow -lt $until) {} ; 'finished'"
        memory = 256 * 1024 * 1024
        cpu = 1
        processes = 2
    policy = SandboxPolicy(
        executable=str(shell),
        args=["-NoProfile", "-NonInteractive", "-Command", command],
        working_dir=str(tmp_path),
        timeout_seconds=15,
        max_memory_bytes=memory,
        max_cpu_time_seconds=cpu,
        max_processes=processes,
    )
    result = run(policy)
    assert not result.timed_out, result
    if resource == "processes":
        assert result.exit_code == 0, result.stderr
        assert result.stdout.strip() == "blocked"
    elif resource == "memory":
        assert result.memory_limit_hit or result.exit_code != 0, result
        assert "allocated" not in result.stdout
    else:
        assert result.exit_code != 0 and "finished" not in result.stdout


@pytest.mark.skipif(sys.platform != "win32" or executable_path() is None,
                    reason="Windows Sandbox is unavailable")
def test_real_vm_rejects_descendant_that_retains_output_pipes(tmp_path):
    child = "import time; time.sleep(120)"
    parent = (
        "import subprocess,sys; "
        f"subprocess.Popen([sys.executable,'-c',{child!r}]); "
        "print('parent-exit')"
    )
    policy = SandboxPolicy(
        executable=str(Path(sys.executable).resolve()),
        args=["-I", "-c", parent],
        working_dir=str(tmp_path),
        timeout_seconds=10,
        max_processes=2,
        max_memory_bytes=256 * 1024 * 1024,
    )
    result = run(policy)
    assert result.exit_code != 0
    assert not result.timed_out
    assert "retained output pipes" in result.stderr

"""Qualify the configured ProcessSandbox VM against an existing Python project.

Runs genuine guest processes. Does not provision a VM profile, approve an
operation, mutate the project, or substitute for the Runtime's Work journal.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

from nous_runtime.kernel.linux_vm import load_profile
from nous_runtime.kernel.sandbox import ProcessSandbox, SandboxPolicy


def qualify(workspace: Path, progress: Path | None = None) -> dict:
    root, profile = load_profile()
    workspace = workspace.resolve(strict=True)
    results = {}

    def execute(name: str, args: list[str], **kwargs):
        policy = SandboxPolicy(
            **{
                "executable": sys.executable,
                "args": args,
                "working_dir": str(workspace),
                "read_allowed_paths": [str(workspace)],
                "timeout_seconds": 30,
                "max_memory_bytes": 256 * 1024**2,
                "max_processes": 1,
                **kwargs,
            }
        )
        result = ProcessSandbox(policy).run()
        results[name] = dataclasses.asdict(result)
        if progress is not None:
            with progress.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"case": name, **results[name]}) + "\n")
        return result

    with tempfile.TemporaryDirectory(prefix="apeir-vm-qualification-") as temporary:
        temporary = Path(temporary)
        sentinel = temporary / "host-only.txt"
        sentinel.write_text("FAKE_ONLY_HOST_SENTINEL")
        name = "APEIR_VM_FAKE_HOST_ONLY"
        original = os.environ.get(name)
        os.environ[name] = "FAKE_ONLY_NEVER_INHERIT"
        code = f"""
import json,os,socket,errno
from pathlib import Path
assert os.getuid() == 1000
assert {name!r} not in os.environ
assert not Path({str(sentinel)!r}).exists()
assert not Path('/proc/1/environ').exists()
try: Path('/control/request.json').read_bytes()
except PermissionError: pass
else: raise AssertionError('guest control secret exposed')
try: Path('/project/forbidden-write.txt').write_text('bad')
except PermissionError: pass
else: raise AssertionError('project was writable')
try: os.setuid(0)
except PermissionError: pass
else: raise AssertionError('privileges could be elevated')
interfaces=[line.split(':')[0].strip() for line in Path('/proc/net/dev').read_text().splitlines()[2:]]
assert interfaces == ['lo'], interfaces
try: socket.create_connection(('198.51.100.1',443),timeout=1)
except OSError: pass
else: raise AssertionError('network egress was available')
try: os.fork()
except OSError as exc: assert exc.errno == errno.EAGAIN
else: raise AssertionError('process budget was bypassed')
print(json.dumps({{'uid':os.getuid(),'interfaces':interfaces,'boundaries':'PASS'}}))
"""
        try:
            boundary = execute("boundary_rejection", ["-c", code])
        finally:
            if original is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = original
        assert boundary.success, boundary.stderr
        assert sentinel.read_text() == "FAKE_ONLY_HOST_SENTINEL"
        assert not (workspace / "forbidden-write.txt").exists()

        memory = execute(
            "memory_budget",
            [
                "-c",
                """
try: bytearray(1024**3)
except MemoryError: print('memory budget enforced')
else: raise AssertionError('memory budget bypassed')
""",
            ],
        )
        assert memory.success, memory.stderr
        output = execute(
            "output_budget", ["-c", 'print("x"*1000000)'], max_output_bytes=1024
        )
        assert output.output_truncated and not output.success
        cancel = temporary / "cancel"
        timer = threading.Timer(12, lambda: cancel.touch())
        timer.start()
        try:
            cancelled = execute(
                "cancellation",
                ["-c", "import time; time.sleep(120)"],
                cancel_file=str(cancel),
            )
        finally:
            timer.cancel()
            timer.join()
        assert cancelled.exit_code == 130 and not cancelled.success
        descendant = execute(
            "detached_descendant_cleanup",
            [
                "-c",
                """
import subprocess,sys
subprocess.Popen([sys.executable,'-c','import os,time; os.setsid(); time.sleep(120)'],
                 stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
print('parent completed; VM teardown must terminate detached guest child')
""",
            ],
            max_processes=4,
        )
        assert descendant.success, descendant.stderr
        rejected = execute(
            "write_grant_rejection",
            ["-c", 'print("must not run")'],
            write_allowed_paths=[str(workspace)],
        )
        assert rejected.availability_state == "unavailable"
        assert not rejected.stdout
        test = execute("project_unittest", ["-m", "unittest", "discover", "-s", "."])
        # A failing project is valid execution evidence. Never rewrite its
        # assertions, source or result merely to obtain a green qualification.
        assert test.availability_state == "available" and test.exit_code in (0, 1), (
            test.stderr
        )

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    return {
        "scope": "Linux x86_64 pinned CPython, read-only project; no host shell or network",
        "profile_sha256": digest(root / "profile.json"),
        "python_version": profile["python_version"],
        "runtime_source_sha256": {
            "adapter": digest(
                Path(__file__).parents[2] / "nous_runtime/kernel/linux_vm.py"
            ),
            "guest": digest(
                Path(__file__).parents[2] / "nous_runtime/kernel/linux_vm_guest.py"
            ),
        },
        "results": results,
        "physical_validation": "NOT_RUN",
        "windows_installation": "NOT_RUN",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    args.report.write_text(
        json.dumps(qualify(args.workspace, args.report.with_suffix(".jsonl")), indent=2)
        + "\n"
    )
    print(f"VM qualification evidence: {args.report}")


if __name__ == "__main__":
    main()

"""Trusted PID 1 controller for the optional Linux read-only test VM.

This file runs in the guest, never as a host command executor. Work state,
authorization and durable results remain with the existing Runtime.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac
import json
import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path


def _guest_environment() -> bool:
    """Accidental host invocation must never reach execution or reboot."""
    if (
        sys.platform != "linux"
        or os.getuid() != 0
        or sys.argv[0] != "/control/runner.py"
    ):
        return False
    try:
        return "apeir.readonly_test_vm=1" in Path("/proc/cmdline").read_text().split()
    except OSError:
        return False


def main() -> None:
    if not _guest_environment():
        raise RuntimeError("Guest controller requires the isolated VM init")
    import resource

    request = json.loads(open("/control/request.json", encoding="utf-8").read())
    key = bytes.fromhex(request.pop("key"))

    def emit(kind: str, value: dict) -> None:
        body = json.dumps(
            {"kind": kind, "nonce": request["nonce"], **value},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        signature = hmac.new(key, body, hashlib.sha256).hexdigest()
        print(
            "APEIR_VM:" + signature + ":" + base64.b64encode(body).decode(), flush=True
        )

    emit("ready", {})
    # The host sends GO only after authenticating READY. If it dies during the
    # parent-death-signal setup race, no untrusted code can start in the guest.
    selector = selectors.DefaultSelector()
    selector.register(sys.stdin, selectors.EVENT_READ)
    if not selector.select(request["timeout_seconds"]):
        return
    line = sys.stdin.readline().strip()
    prefix = "GO:" + request["nonce"] + ":"
    if not line.startswith(prefix):
        return
    remaining = min(float(line[len(prefix) :]), request["timeout_seconds"])
    if remaining <= 0:
        return

    def restrict() -> None:
        os.setsid()
        resource.setrlimit(resource.RLIMIT_AS, (request["memory"], request["memory"]))
        resource.setrlimit(resource.RLIMIT_CPU, (request["cpu"], request["cpu"]))
        resource.setrlimit(
            resource.RLIMIT_NPROC, (request["processes"], request["processes"])
        )
        resource.setrlimit(
            resource.RLIMIT_FSIZE, (request["file_size"], request["file_size"])
        )
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        os.setgroups([])
        os.setgid(1000)
        os.setuid(1000)
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
            os._exit(126)

    environment = {
        "PATH": "/runtime/bin:/bin",
        "HOME": "/tmp",
        "TMPDIR": "/tmp",
        "PYTHONHOME": "/runtime",
        "LD_LIBRARY_PATH": "/runtime/lib",
        "PYTHONDONTWRITEBYTECODE": "1",
        **request["env"],
    }
    # No host environment, descriptors, credentials or mount is inherited.
    child = subprocess.Popen(
        ["/runtime/bin/python", *request["args"]],
        cwd="/project",
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=restrict,
    )
    emit("started", {"pid": child.pid})
    # Input is bounded by the host. Avoid a pipe-write deadlock before draining
    # stdout: the guest input is a regular, private, read-only file instead.
    child.stdin.close()
    selector.close()
    selector = selectors.DefaultSelector()
    streams = [bytearray(), bytearray()]
    for index, pipe in enumerate((child.stdout, child.stderr)):
        os.set_blocking(pipe.fileno(), False)
        selector.register(pipe, selectors.EVENT_READ, index)
    deadline = time.monotonic() + remaining
    timed_out = truncated = False
    size = 0
    while selector.get_map():
        if time.monotonic() >= deadline:
            timed_out = True
            break
        for entry, _ in selector.select(0.05):
            block = os.read(entry.fileobj.fileno(), 65536)
            if not block:
                selector.unregister(entry.fileobj)
                entry.fileobj.close()
                continue
            available = max(0, request["output"] - size)
            streams[entry.data].extend(block[:available])
            size += min(len(block), available)
            if len(block) > available:
                truncated = True
        if truncated:
            break
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    child.wait()
    selector.close()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    emit(
        "result",
        {
            "exit_code": child.returncode,
            "stdout": base64.b64encode(streams[0]).decode(),
            "stderr": base64.b64encode(streams[1]).decode(),
            "timed_out": timed_out,
            "output_truncated": truncated,
            "peak_memory_bytes": int(usage.ru_maxrss) * 1024,
        },
    )


if __name__ == "__main__":
    try:
        main()
    finally:
        # Untrusted descendants cannot survive a disposable VM's shutdown.
        # A direct host invocation cannot reach the guest reboot syscall.
        if _guest_environment():
            ctypes.CDLL(None, use_errno=True).reboot(0x01234567)

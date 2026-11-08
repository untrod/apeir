"""Build an operator-reviewed read-only Python VM profile from local inputs.

No downloads, package installation, root privileges or workload execution.
Input binaries and the Python installation must already be trusted. The output
digest is a deployment setting, never a field in Work, Layout or Provider data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import re
import shutil
import stat
import subprocess
import sys
import sysconfig
from pathlib import Path

from nous_runtime.kernel.linux_vm import cpio


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def build(args: argparse.Namespace) -> dict:
    output = args.output.absolute()
    output.mkdir(mode=0o700)  # Never overwrite an existing reviewed profile.
    library_directory = output / "libraries"
    library_directory.mkdir(mode=0o700)
    for source in args.qemu_libraries.iterdir():
        if source.is_file():
            shutil.copyfile(source, library_directory / source.name)
    data_directory = output / "data"
    data_directory.mkdir(mode=0o700)
    for source in args.qemu_data.iterdir():
        if source.is_file():
            shutil.copyfile(source, data_directory / source.name)
    inputs = {"qemu": args.qemu, "kernel": args.kernel, "firmware": args.firmware}
    for name, source in inputs.items():
        shutil.copyfile(source, output / name)
        (output / name).chmod(0o700 if name == "qemu" else 0o600)

    files: dict[str, tuple[bytes, int]] = {}

    def add(name: str, data: bytes, mode: int = 0o444) -> None:
        parent = Path(name).parent
        for directory in reversed((parent, *parent.parents)):
            if str(directory) != ".":
                files.setdefault(directory.as_posix(), (b"", stat.S_IFDIR | 0o555))
        if name in files and files[name][0] != data:
            raise ValueError("conflicting guest runtime paths")
        files[name] = (data, stat.S_IFREG | mode)

    executable = Path(sys.executable).resolve(strict=True)
    stdlib = Path(sysconfig.get_path("stdlib"))
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    add("runtime/bin/python", executable.read_bytes(), 0o555)
    trusted_elfs = [executable]
    for path in sorted(stdlib.rglob("*")):
        relative = path.relative_to(stdlib)
        if any(
            part
            in {
                "site-packages",
                "dist-packages",
                "__pycache__",
                "test",
                "tests",
                "ensurepip",
                "idlelib",
                "tkinter",
            }
            for part in relative.parts
        ):
            continue
        if path.name.startswith("_tkinter."):
            continue  # This headless test profile has no GUI/display service.
        if path.is_file() and path.suffix in {".py", ".so", ".json", ".txt", ".pem"}:
            add(
                f"runtime/lib/python{version}/" + relative.as_posix(), path.read_bytes()
            )
            if path.suffix == ".so":
                trusted_elfs.append(path)
    # ldd is used only for the operator's trusted interpreter/stdlib DSOs,
    # never for a binary supplied by the project or a model.
    for elf in trusted_elfs:
        command = subprocess.run(
            ["/usr/bin/ldd", str(elf)],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )
        if "not found" in command.stdout:
            raise ValueError("trusted Python dependency is unavailable")
        for name in re.findall(
            r"(?:=>\s+|^\s*)(/[^\s]+)", command.stdout, re.MULTILINE
        ):
            path = Path(name)
            add(path.as_posix().lstrip("/"), path.read_bytes(), 0o555)
    add("bin/busybox", args.busybox.read_bytes(), 0o555)
    # A headless guest has no disk/network interrupts to guarantee early
    # entropy. Feed the host's OS random source through a dedicated virtio RNG,
    # never through an inherited credential or a predictable fixed seed.
    for module in (
        "drivers/virtio/virtio_mmio.ko.xz",
        "drivers/char/hw_random/virtio-rng.ko.xz",
    ):
        source = args.guest_modules / "kernel" / module
        add(
            "modules/" + source.name.removesuffix(".xz"),
            lzma.decompress(source.read_bytes()),
        )
    controller = (
        Path(__file__).resolve().parents[2] / "nous_runtime/kernel/linux_vm_guest.py"
    )
    add("control/runner.py", controller.read_bytes())
    # No shell from the project is evaluated; this is a fixed trusted init.
    init = """#!/bin/busybox sh
/bin/busybox mount -t proc -o hidepid=2 proc /proc || exit 1
/bin/busybox mount -t devtmpfs devtmpfs /dev || exit 1
/bin/busybox mount -t tmpfs -o mode=1777,nosuid,nodev tmpfs /tmp || exit 1
/bin/busybox chmod 600 /dev/ttyS0
exec </dev/ttyS0 >/dev/ttyS0 2>&1
/bin/busybox stty -F /dev/ttyS0 raw -echo
/bin/busybox insmod /modules/virtio_mmio.ko || exit 1
/bin/busybox insmod /modules/virtio-rng.ko || exit 1
/bin/busybox echo APEIR_GUEST_RUNTIME_START
export PYTHONHOME=/runtime
export LD_LIBRARY_PATH=/runtime/lib
/runtime/bin/python -I -S /control/runner.py
/bin/busybox reboot -f
"""
    add("init", init.encode(), 0o555)
    for name in ("proc", "dev", "tmp", "project"):
        files[name] = (b"", stat.S_IFDIR | 0o555)
    files["control"] = (b"", stat.S_IFDIR | 0o700)
    (output / "runtime.cpio.gz").write_bytes(
        cpio([(k, v[0], v[1]) for k, v in sorted(files.items())])
    )
    inventory = {
        p.relative_to(output).as_posix(): digest(p)
        for p in sorted(output.rglob("*"))
        if p.is_file()
    }
    profile = {
        "schema_version": 1,
        "architecture": "x86_64",
        "qemu": "qemu",
        "kernel": "kernel",
        "firmware": "firmware",
        "image": "runtime.cpio.gz",
        "libraries": "libraries",
        "data": "data",
        "python_sha256": digest(executable),
        "python_version": sys.version.split()[0],
        "guest_controller_sha256": digest(controller),
        "files": inventory,
    }
    target = output / "profile.json"
    target.write_text(json.dumps(profile, sort_keys=True, indent=2) + "\n")
    return {
        "profile": str(target),
        "sha256": digest(target),
        "python_sha256": profile["python_sha256"],
        "python_version": profile["python_version"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "qemu",
        "kernel",
        "firmware",
        "busybox",
        "qemu-libraries",
        "qemu-data",
        "guest-modules",
        "output",
    ):
        parser.add_argument("--" + name, required=True, type=Path)
    print(json.dumps(build(parser.parse_args()), indent=2))


if __name__ == "__main__":
    main()

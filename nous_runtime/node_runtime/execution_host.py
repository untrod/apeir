"""Truthful execution-host inventory and requirement preflight.

This module reports host facts.  It does not grant, mint, or imply APEIR
capabilities; admission and authorization remain with the existing policy and
Kernel paths.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import re
import shutil
import sys
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nous_runtime.capability.sandbox import run_process_strict


_TOOL_COMMANDS: dict[str, tuple[tuple[str, ...], ...]] = {
    "git": (("git", "--version"),),
    "rustc": (("rustc", "--version"),),
    "cargo": (("cargo", "--version"),),
    "node": (("node", "--version"),),
    "npm": (("npm.cmd", "--version"), ("npm", "--version")),
    "cmake": (("cmake", "--version"),),
    "ninja": (("ninja", "--version"),),
    "docker": (("docker", "--version"),),
    "podman": (("podman", "--version"),),
    "esptool": (("esptool", "version"), ("esptool.py", "version")),
    "idf.py": (("idf.py", "--version"),),
    "openocd": (("openocd", "--version"),),
    "kicad-cli": (("kicad-cli", "--version"),),
}
_TOOL_INVENTORY_CACHE_SECONDS = 300.0
_TOOL_INVENTORY_CACHE: dict[str, dict[str, Any]] | None = None
_TOOL_INVENTORY_CACHE_AT = 0.0
_TOOL_INVENTORY_CACHE_LOCK = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_architecture(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    if normalized in {"arm64", "aarch64", "armv8", "armv8l"}:
        return "arm64"
    if normalized in {"amd64", "x86-64", "x64"}:
        return "amd64"
    if normalized in {"x86", "i386", "i686"}:
        return "x86"
    return normalized


def collect_tool_inventory(*, refresh: bool = False) -> dict[str, dict[str, Any]]:
    """Probe required and optional engineering tools without invoking a shell."""
    global _TOOL_INVENTORY_CACHE, _TOOL_INVENTORY_CACHE_AT
    now = time.monotonic()
    with _TOOL_INVENTORY_CACHE_LOCK:
        if (
            not refresh
            and _TOOL_INVENTORY_CACHE is not None
            and now - _TOOL_INVENTORY_CACHE_AT < _TOOL_INVENTORY_CACHE_SECONDS
        ):
            return deepcopy(_TOOL_INVENTORY_CACHE)
        inventory = {
            "python": _probe_python(),
            "pip": _probe_pip(),
        }
        for name, candidates in _TOOL_COMMANDS.items():
            inventory[name] = _probe_command(candidates)
        _TOOL_INVENTORY_CACHE = deepcopy(inventory)
        _TOOL_INVENTORY_CACHE_AT = time.monotonic()
        return inventory


def _probe_python() -> dict[str, Any]:
    return {
        "available": True,
        "path": str(Path(sys.executable).resolve()),
        "version": platform.python_version(),
        "version_output": f"Python {platform.python_version()}",
    }


def _probe_pip() -> dict[str, Any]:
    result = _run_version_command((sys.executable, "-m", "pip", "--version"))
    return {
        "available": result[0],
        "path": str(Path(sys.executable).resolve()),
        "version": _extract_version(result[1]),
        "version_output": result[1],
        "invocation": "python -m pip",
    }


def _probe_command(candidates: tuple[tuple[str, ...], ...]) -> dict[str, Any]:
    for candidate in candidates:
        executable = shutil.which(candidate[0])
        if executable is None:
            continue
        available, output = _run_version_command((executable, *candidate[1:]))
        return {
            "available": True,
            "path": str(Path(executable).resolve()),
            "version": _extract_version(output),
            "version_output": output,
            "version_probe_ok": available,
        }
    return {
        "available": False,
        "path": "",
        "version": "",
        "version_output": "",
        "version_probe_ok": False,
    }


def _run_version_command(command: tuple[str, ...]) -> tuple[bool, str]:
    try:
        completed = run_process_strict(
            list(command),
            cwd=os.getcwd(),
            timeout_seconds=5,
            max_output_bytes=4096,
        )
    except (OSError, RuntimeError, ValueError):
        return False, ""
    output = (completed.stdout or completed.stderr).strip().splitlines()
    return completed.ok, (output[0][:512] if output else "")


def _extract_version(value: str) -> str:
    match = re.search(r"(?<!\d)(\d+(?:\.\d+){0,3}(?:[-+._][0-9A-Za-z.-]+)?)", value)
    return match.group(1) if match else ""


def collect_execution_host_inventory(
    resources: dict[str, Any] | None = None,
    *,
    refresh_tools: bool = False,
) -> dict[str, Any]:
    """Collect a machine-readable inventory of facts about this execution host."""
    resources = dict(resources or {})
    process_arch = _normalize_architecture(platform.machine())
    physical_arch = _normalize_architecture(
        os.environ.get("PROCESSOR_ARCHITEW6432") or platform.machine()
    )
    io = _probe_physical_io()
    return {
        "schema": "apeir.execution-host-inventory/v1",
        "measured_at": _utc_now(),
        "authority": "none",
        "grants_capabilities": False,
        "host": {
            "os": resources.get("os") or platform.system(),
            "os_version": resources.get("os_version") or platform.version(),
            "architecture": physical_arch,
            "process_architecture": process_arch,
            "cpu": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", ""),
            "cpu_logical": resources.get("cpu_logical") or os.cpu_count() or 1,
            "memory_total_bytes": resources.get("memory_total_bytes", 0),
            "memory_available_bytes": resources.get("memory_available_bytes", 0),
            "storage_total_bytes": resources.get("disk_total_bytes", 0),
            "storage_free_bytes": resources.get("disk_free_bytes", 0),
            "network_addresses": list(resources.get("network_addresses") or []),
        },
        "tools": collect_tool_inventory(refresh=refresh_tools),
        "physical_io": io,
    }


def _probe_physical_io() -> dict[str, Any]:
    if os.name != "nt":
        return {
            "usb_devices": [],
            "com_ports": [],
            "serial": {
                "available": importlib.util.find_spec("serial") is not None,
                "python_serial_available": importlib.util.find_spec("serial")
                is not None,
                "probe_source": "python-module",
            },
        }

    usb_devices, usb_probe_source = _probe_windows_usb_devices()
    com_ports = _probe_windows_com_registry()
    python_serial = importlib.util.find_spec("serial") is not None
    return {
        "usb_devices": usb_devices,
        "usb_probe_source": usb_probe_source,
        "com_ports": com_ports,
        "serial": {
            "available": bool(com_ports) or python_serial,
            "ports_detected": bool(com_ports),
            "python_serial_available": python_serial,
            "probe_source": "windows-registry",
        },
    }


def _probe_windows_usb_devices() -> tuple[list[dict[str, Any]], str]:
    """List present USB devices without exposing per-device serial numbers."""
    try:
        import ctypes
        from ctypes import wintypes

        class Guid(ctypes.Structure):
            _fields_ = [
                ("data1", wintypes.DWORD),
                ("data2", wintypes.WORD),
                ("data3", wintypes.WORD),
                ("data4", ctypes.c_ubyte * 8),
            ]

        class DeviceInfoData(ctypes.Structure):
            _fields_ = [
                ("size", wintypes.DWORD),
                ("class_guid", Guid),
                ("device_instance", wintypes.DWORD),
                ("reserved", ctypes.c_void_p),
            ]

        setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
        get_devices = setupapi.SetupDiGetClassDevsW
        get_devices.argtypes = [
            ctypes.POINTER(Guid),
            wintypes.LPCWSTR,
            wintypes.HWND,
            wintypes.DWORD,
        ]
        get_devices.restype = wintypes.HANDLE
        enumerate_device = setupapi.SetupDiEnumDeviceInfo
        enumerate_device.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(DeviceInfoData),
        ]
        enumerate_device.restype = wintypes.BOOL
        get_instance_id = setupapi.SetupDiGetDeviceInstanceIdW
        get_instance_id.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(DeviceInfoData),
            wintypes.LPWSTR,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        get_instance_id.restype = wintypes.BOOL
        destroy_devices = setupapi.SetupDiDestroyDeviceInfoList
        destroy_devices.argtypes = [wintypes.HANDLE]
        destroy_devices.restype = wintypes.BOOL

        devices_handle = get_devices(None, "USB", None, 0x00000006)
        if devices_handle == ctypes.c_void_p(-1).value:
            raise OSError(ctypes.get_last_error(), "SetupDiGetClassDevsW failed")
        counts: dict[str, int] = {}
        try:
            index = 0
            while True:
                device = DeviceInfoData()
                device.size = ctypes.sizeof(DeviceInfoData)
                if not enumerate_device(devices_handle, index, ctypes.byref(device)):
                    if ctypes.get_last_error() == 259:
                        break
                    raise OSError(
                        ctypes.get_last_error(), "SetupDiEnumDeviceInfo failed"
                    )
                index += 1
                buffer = ctypes.create_unicode_buffer(1024)
                required = wintypes.DWORD()
                if not get_instance_id(
                    devices_handle,
                    ctypes.byref(device),
                    buffer,
                    len(buffer),
                    ctypes.byref(required),
                ):
                    continue
                parts = buffer.value.split("\\")
                hardware_id = parts[1] if len(parts) > 1 else parts[0]
                counts[hardware_id] = counts.get(hardware_id, 0) + 1
        finally:
            destroy_devices(devices_handle)
        return (
            [
                {"hardware_id": key, "instances": counts[key], "present": True}
                for key in sorted(counts, key=str.lower)
            ],
            "windows-setupapi-present",
        )
    except (AttributeError, ImportError, OSError, ValueError):
        return _probe_windows_usb_registry(), "windows-registry-known"


def _probe_windows_usb_registry() -> list[dict[str, Any]]:
    try:
        import winreg

        root = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Enum\USB"
        )
    except (ImportError, OSError):
        return []
    devices: list[dict[str, Any]] = []
    try:
        index = 0
        while True:
            try:
                hardware_id = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            instances = 0
            try:
                child = winreg.OpenKey(root, hardware_id)
                try:
                    instances = winreg.QueryInfoKey(child)[0]
                finally:
                    child.Close()
            except OSError:
                pass
            devices.append(
                {"hardware_id": hardware_id, "instances": instances, "present": None}
            )
    finally:
        root.Close()
    return sorted(devices, key=lambda item: item["hardware_id"].lower())


def _probe_windows_com_registry() -> list[str]:
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM"
        )
    except (ImportError, OSError):
        return []
    ports: set[str] = set()
    try:
        index = 0
        while True:
            try:
                _name, value, _kind = winreg.EnumValue(key, index)
            except OSError:
                break
            index += 1
            if isinstance(value, str) and re.fullmatch(r"COM\d+", value.upper()):
                ports.add(value.upper())
    finally:
        key.Close()
    return sorted(ports, key=lambda item: int(item[3:]))


def evaluate_execution_preflight(
    inventory: dict[str, Any], requirements: dict[str, Any]
) -> dict[str, Any]:
    """Evaluate host facts against simple architecture and tool requirements."""
    if not isinstance(requirements, dict):
        raise ValueError("preflight requirements must be an object")
    reasons: list[str] = []
    requested_arch = requirements.get("architecture")
    actual_arch = _normalize_architecture(
        str((inventory.get("host") or {}).get("architecture") or "")
    )
    if requested_arch:
        expected_arch = _normalize_architecture(str(requested_arch))
        if actual_arch != expected_arch:
            reasons.append(
                f"architecture mismatch: requires {expected_arch}, host is {actual_arch or 'unknown'}"
            )

    tools = inventory.get("tools") or {}
    for name, operator, requested_version in _parse_tool_requirements(
        requirements.get("tools", [])
    ):
        fact = tools.get(name) or {}
        if not fact.get("available"):
            reasons.append(f"tool {name} missing")
            continue
        if operator and requested_version:
            actual_version = str(fact.get("version") or "")
            if not actual_version:
                reasons.append(
                    f"tool {name} version unknown; requires {operator} {requested_version}"
                )
            elif not _version_satisfies(actual_version, operator, requested_version):
                reasons.append(
                    f"tool {name} {actual_version} does not satisfy {operator} {requested_version}"
                )

    return {
        "schema": "apeir.execution-preflight/v1",
        "evaluated_at": _utc_now(),
        "status": "INELIGIBLE" if reasons else "ELIGIBLE",
        "eligible": not reasons,
        "reasons": reasons,
        "requirements": requirements,
        "authority": "none",
        "grants_capabilities": False,
    }


def _parse_tool_requirements(
    value: Any,
) -> list[tuple[str, str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("preflight tools must be a list")
    parsed: list[tuple[str, str, str]] = []
    pattern = re.compile(
        r"^([A-Za-z0-9_.-]+)(?:\s*(>=|<=|==|>|<)\s*([0-9][0-9A-Za-z.+_-]*))?$"
    )
    for item in value:
        if not isinstance(item, str):
            raise ValueError("each preflight tool requirement must be a string")
        match = pattern.fullmatch(item.strip())
        if match is None:
            raise ValueError(f"invalid tool requirement: {item}")
        parsed.append(
            (match.group(1).lower(), match.group(2) or "", match.group(3) or "")
        )
    return parsed


def _version_satisfies(actual: str, operator: str, required: str) -> bool:
    actual_tuple = _version_tuple(actual)
    required_tuple = _version_tuple(required)
    width = max(len(actual_tuple), len(required_tuple))
    left = actual_tuple + (0,) * (width - len(actual_tuple))
    right = required_tuple + (0,) * (width - len(required_tuple))
    return {
        ">=": left >= right,
        "<=": left <= right,
        "==": left == right,
        ">": left > right,
        "<": left < right,
    }[operator]


def _version_tuple(value: str) -> tuple[int, ...]:
    match = re.match(r"\d+(?:\.\d+)*", value)
    if match is None:
        return ()
    return tuple(int(part) for part in match.group(0).split("."))


__all__ = [
    "collect_execution_host_inventory",
    "collect_tool_inventory",
    "evaluate_execution_preflight",
]

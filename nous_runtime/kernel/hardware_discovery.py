"""
Hardware Discovery — Device Provider implementation for local hardware.

This module implements the Discovery Provider interface from the
Provider SDK, discovering CPU, GPU, and accelerator devices on the
local machine and producing Device objects using the canonical
device model (nous_runtime.kernel.device_model).

Supported backends:
  - CPU: psutil (cores, memory, topology, NUMA)
  - NVIDIA: pynvml (CUDA GPUs — VRAM, SM count, driver version, PCIe topology)
  - AMD: ROCm SMI / AMD SMI (preliminary — interface contract defined)
  - Qualcomm: QNN detection on Windows ARM64 (preliminary)
  - Apple: Metal/ANE detection (preliminary — interface contract defined)

Design principle:
  - Each vendor backend is a separate discover() function
  - All produce Device objects with the standard DeviceSpec/DeviceStatus
  - Discovery is idempotent — re-running updates status, preserves device_id
  - No exceptions escape — discovery failures are logged at WARNING and
    the backend returns an empty list
"""

from __future__ import annotations

import logging
import os
import platform
import time
from typing import Optional

from nous_runtime.kernel.device_model import (
    Device,
    DevicePhase,
    DeviceSpec,
    DeviceStatus,
    DeviceType,
    TopologyLink,
    _stable_device_id,
    DEVICE_CLASS_CPU,
    DEVICE_CLASS_NVIDIA_CUDA,
    DEVICE_CLASS_NVIDIA_CUDA_HIGH_MEM,
    DEVICE_CLASS_NVIDIA_JETSON,
)
from nous_runtime.kernel.resource_model import ResourceVector, ResourceSlice

log = logging.getLogger("nous.kernel.hardware")


# ────────────────────────────────────────────────────────────
# CPU Discovery
# ────────────────────────────────────────────────────────────


def discover_cpu_devices() -> list[Device]:
    """Discover CPU devices on the local machine."""
    try:
        import psutil
    except ImportError:
        log.warning("psutil not available — CPU discovery limited to os.cpu_count()")
        return [_basic_cpu_device()]

    devices = []
    hostname = platform.node()
    cpu_count = os.cpu_count() or psutil.cpu_count(logical=True) or 1
    mem = psutil.virtual_memory()
    disk_usage = _get_total_disk_bytes()

    # Detect NUMA topology if available
    numa_nodes: dict[int, list[int]] = {}
    numa_node_count = _detect_numa_nodes()
    for i in range(cpu_count):
        node = _get_numa_node(i) if numa_node_count > 0 else 0
        numa_nodes.setdefault(node, []).append(i)

    # One device per NUMA node (or one device total if no NUMA info)
    for node_id, cores in (
        numa_nodes.items() if numa_nodes else {0: list(range(cpu_count))}.items()
    ):
        core_count = len(cores)
        node_ram = mem.total // max(1, len(numa_nodes)) if numa_nodes else mem.total
        device_name = f"cpu-numa{node_id}" if numa_nodes else "cpu-0"
        stable_id = _stable_device_id("cpu", hostname, device_name)

        available = ResourceVector(
            cpu_cores_millis=core_count * 1000,
            ram_bytes=node_ram,
            storage_bytes=disk_usage,
        )

        spec = DeviceSpec(
            device_type=DeviceType.CPU,
            vendor=platform.processor() or "unknown",
            model=platform.machine(),
            architecture=platform.machine(),
            driver_version="",
            total_resources=available,
            capabilities=("inference", "embedding", "tokenization"),
            supported_engines=("llama.cpp", "onnx", "openvino"),
            supported_dtypes=("fp32", "fp16", "int8", "int4"),
            compute_units=core_count,
            numa_node=node_id if numa_nodes else -1,
        )

        device = Device(
            device_id=stable_id,
            spec=spec,
            status=DeviceStatus(
                phase=DevicePhase.READY,
                available=available,
                utilization_percent=psutil.cpu_percent(interval=0.1),
                memory_utilization_percent=mem.percent,
                uptime_seconds=time.time() - psutil.boot_time(),
            ),
            device_class=DEVICE_CLASS_CPU,
            labels={"hostname": hostname, "numa_node": str(node_id)},
        )
        devices.append(device)

    if not devices:
        devices.append(_basic_cpu_device())

    return devices


def _basic_cpu_device() -> Device:
    """Minimal CPU device without psutil."""
    cpu_count = os.cpu_count() or 1
    memory_bytes = _get_physical_memory_bytes()
    disk_bytes = _get_total_disk_bytes()
    return Device(
        device_id=_stable_device_id("cpu", platform.node(), "cpu-0"),
        spec=DeviceSpec(
            device_type=DeviceType.CPU,
            vendor=platform.processor() or "unknown",
            model=platform.machine(),
            architecture=platform.machine(),
            total_resources=ResourceVector(
                cpu_cores_millis=cpu_count * 1000,
                ram_bytes=memory_bytes,
                storage_bytes=disk_bytes,
            ),
            capabilities=("inference",),
            supported_engines=("llama.cpp", "onnx"),
            supported_dtypes=("fp32",),
            compute_units=cpu_count,
        ),
        status=DeviceStatus(
            phase=DevicePhase.READY,
            available=ResourceVector(
                cpu_cores_millis=cpu_count * 1000,
                ram_bytes=memory_bytes,
                storage_bytes=disk_bytes,
            ),
        ),
        device_class=DEVICE_CLASS_CPU,
    )


def _get_physical_memory_bytes() -> int:
    """Read physical memory from the host OS; return 0 when it is unknown."""

    if os.name == "nt":
        try:
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong),
                    ("memory_load", ctypes.c_ulong),
                    ("total_physical", ctypes.c_ulonglong),
                    ("available_physical", ctypes.c_ulonglong),
                    ("total_page_file", ctypes.c_ulonglong),
                    ("available_page_file", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong),
                    ("available_virtual", ctypes.c_ulonglong),
                    ("available_extended_virtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.length = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.total_physical)
        except (AttributeError, OSError, ValueError):
            return 0
    try:
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        return max(0, pages * page_size)
    except (AttributeError, OSError, TypeError, ValueError):
        pass
    try:
        for line in open("/proc/meminfo", encoding="utf-8"):
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _detect_numa_nodes() -> int:
    """Detect the number of NUMA nodes. Returns 0 if unknown."""
    # Linux: /sys/devices/system/node/node*
    try:
        nodes = [
            d for d in os.listdir("/sys/devices/system/node/") if d.startswith("node")
        ]
        return len(nodes)
    except (FileNotFoundError, PermissionError):
        pass
    # Windows: could use GetNumaHighestNodeNumber via ctypes
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        highest = ctypes.c_ulong()
        if kernel32.GetNumaHighestNodeNumber(ctypes.byref(highest)):
            return highest.value + 1
    except Exception:
        pass
    return 0


def _get_numa_node(cpu_index: int) -> int:
    """Get the NUMA node for a given CPU index."""
    # Linux
    try:
        path = f"/sys/devices/system/cpu/cpu{cpu_index}/topology/physical_package_id"
        with open(path) as f:
            return int(f.read().strip())
    except Exception:
        pass
    return 0


def _get_total_disk_bytes() -> int:
    """Get total disk capacity in bytes."""
    try:
        import shutil

        usage = shutil.disk_usage(os.getcwd())
        return usage.total
    except Exception:
        return 1_000_000_000_000  # Assume 1TB


# ────────────────────────────────────────────────────────────
# NVIDIA GPU Discovery (NVML)
# ────────────────────────────────────────────────────────────


def discover_nvidia_devices() -> list[Device]:
    """
    Discover NVIDIA GPU devices via NVML (NVIDIA Management Library).

    NVML provides stable GPU UUIDs that survive reboots, PCIe topology,
    driver/runtime versions, power/thermal telemetry, and ECC error counts.

    Reference: https://docs.nvidia.com/deploy/nvml-api/
    """
    try:
        import pynvml
    except ImportError:
        log.debug(
            "pynvml not installed — NVIDIA GPU discovery skipped. "
            "Install with: pip install pynvml"
        )
        return []

    try:
        pynvml.nvmlInit()
    except pynvml.NVMLError as exc:
        log.debug("NVML initialization failed (no NVIDIA driver?): %s", exc)
        return []

    devices = []
    hostname = platform.node()

    try:
        device_count = pynvml.nvmlDeviceGetCount()
    except pynvml.NVMLError:
        pynvml.nvmlShutdown()
        return []

    driver_version = _safe_nvml_str(pynvml.nvmlSystemGetDriverVersion)

    for i in range(device_count):
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            device = _build_nvidia_device(handle, i, hostname, driver_version)
            if device:
                devices.append(device)
        except pynvml.NVMLError as exc:
            log.warning("Failed to probe NVIDIA GPU %d: %s", i, exc)
            continue

    # Discover PCIe topology between GPUs
    if len(devices) > 1:
        _add_nvidia_topology(devices)

    try:
        pynvml.nvmlShutdown()
    except pynvml.NVMLError:
        pass

    return devices


def _safe_nvml_str(fn) -> str:
    """Safely call an NVML string function."""
    try:
        result = fn()
        if isinstance(result, bytes):
            return result.decode("utf-8", errors="replace")
        return str(result)
    except Exception:
        return "unknown"


def _safe_nvml_int(fn) -> int:
    """Safely call an NVML int function."""
    try:
        return int(fn())
    except Exception:
        return 0


def _build_nvidia_device(
    handle, index: int, hostname: str, driver_version: str
) -> Optional[Device]:
    """Build a Device from an NVML GPU handle."""
    try:
        import pynvml

        # Stable identity — NVML UUID survives reboots
        uuid_str = _safe_nvml_str(lambda: pynvml.nvmlDeviceGetUUID(handle))
        stable_id = f"dev-nvidia-{uuid_str.replace('GPU-', '').lower()[:16]}"

        # Basic info
        name = _safe_nvml_str(lambda: pynvml.nvmlDeviceGetName(handle))
        total_vram = _safe_nvml_int(
            lambda: pynvml.nvmlDeviceGetMemoryInfo(handle).total
        )
        free_vram = _safe_nvml_int(lambda: pynvml.nvmlDeviceGetMemoryInfo(handle).free)

        # Architecture
        arch = _detect_nv_architecture(handle)

        # PCI info
        pci_bus_id = _safe_nvml_str(lambda: pynvml.nvmlDeviceGetPciInfo(handle).busId)

        # Driver
        cuda_version = _safe_nvml_str(lambda: pynvml.nvmlSystemGetCudaDriverVersion)
        cuda_compute_major, cuda_compute_minor = _get_cuda_compute_capability(handle)

        # Compute
        sm_count = _safe_nvml_int(lambda: pynvml.nvmlDeviceGetNumGpuCores(handle))
        # Telemetry
        try:
            temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
        except pynvml.NVMLError:
            temp = 0
        try:
            power_mw = pynvml.nvmlDeviceGetPowerUsage(handle)  # milliwatts
        except pynvml.NVMLError:
            power_mw = 0
        try:
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            gpu_util = util.gpu
            mem_util = util.memory
        except pynvml.NVMLError:
            gpu_util, mem_util = 0, 0

        # Jetson detection
        is_jetson = (
            "Jetson" in name or "Orin" in name or "Xavier" in name or "Tegra" in name
        )

        # Determine device class
        if is_jetson:
            device_class = DEVICE_CLASS_NVIDIA_JETSON
        elif total_vram >= 16 * 1024 * 1024 * 1024:
            device_class = DEVICE_CLASS_NVIDIA_CUDA_HIGH_MEM
        else:
            device_class = DEVICE_CLASS_NVIDIA_CUDA

        # Capabilities based on compute capability
        capabilities = ["inference", "cuda_graph"]
        if cuda_compute_major >= 8:
            capabilities.append("bf16")
        if cuda_compute_major >= 7:
            capabilities.append("fp16")
        if cuda_compute_major >= 8:
            capabilities.append("sparse")
        capabilities.extend(["fp32", "int8", "int4"])

        # Supported engines
        supported_engines = ["vllm", "tensorrt-llm", "llama.cpp", "onnx"]
        if is_jetson:
            supported_engines = ["llama.cpp", "onnx", "tensorrt"]

        total_resources = ResourceVector(
            device_memory_bytes=total_vram,
            kv_cache_bytes=int(total_vram * 0.8),  # 80% of VRAM available for KV cache
            power_milliwatts=_safe_nvml_int(
                lambda: pynvml.nvmlDeviceGetPowerManagementLimit(handle)
            )
            * 1000,
        )

        spec = DeviceSpec(
            device_type=DeviceType.CUDA,
            vendor="NVIDIA",
            model=name,
            architecture=arch,
            driver_version=f"CUDA {cuda_version}, Driver {driver_version}",
            total_resources=total_resources,
            capabilities=tuple(capabilities),
            supported_engines=tuple(supported_engines),
            supported_dtypes=("fp32", "fp16", "bf16", "int8", "int4"),
            compute_units=sm_count,
            pci_bus_id=pci_bus_id,
        )

        device = Device(
            device_id=stable_id,
            spec=spec,
            status=DeviceStatus(
                phase=DevicePhase.READY,
                available=ResourceVector(
                    device_memory_bytes=free_vram,
                    kv_cache_bytes=int(free_vram * 0.8),
                ),
                temperature_celsius=float(temp),
                power_milliwatts=power_mw,
                utilization_percent=float(gpu_util),
                memory_utilization_percent=float(mem_util),
                uptime_seconds=0.0,  # NVML doesn't expose per-GPU uptime
            ),
            device_class=device_class,
            labels={
                "hostname": hostname,
                "uuid": uuid_str,
                "pci_bus_id": pci_bus_id,
                "compute_capability": f"{cuda_compute_major}.{cuda_compute_minor}",
            },
        )
        return device

    except Exception as exc:
        log.warning("Failed to build NVIDIA device %d: %s", index, exc)
        return None


def _detect_nv_architecture(handle) -> str:
    """Detect NVIDIA GPU architecture from compute capability."""
    major, minor = _get_cuda_compute_capability(handle)
    if major >= 9:
        return (
            "Hopper"
            if major == 9
            else "Blackwell"
            if major >= 10
            else f"sm{major}{minor}"
        )
    if major == 8:
        return "Ampere" if minor >= 0 else f"sm{major}{minor}"
    if major == 7:
        return (
            "Volta" if minor == 0 else "Turing" if minor == 5 else f"sm{major}{minor}"
        )
    if major == 6:
        return "Pascal"
    if major == 5:
        return "Maxwell"
    if major >= 10:
        return "Blackwell"
    return f"sm{major}{minor}"


def _get_cuda_compute_capability(handle) -> tuple[int, int]:
    """Get CUDA compute capability (major, minor)."""
    try:
        import pynvml

        major = pynvml.nvmlDeviceGetCudaComputeCapability(handle)
        return (major[0], major[1])
    except Exception:
        return (0, 0)


def _add_nvidia_topology(devices: list[Device]) -> None:
    """Add PCIe/NVLink topology links between NVIDIA devices."""
    try:
        import pynvml

        for i, dev_a in enumerate(devices):
            for j, dev_b in enumerate(devices):
                if i >= j:
                    continue
                try:
                    handle_a = pynvml.nvmlDeviceGetHandleByIndex(i)
                    handle_b = pynvml.nvmlDeviceGetHandleByIndex(j)
                    # Check P2P accessibility
                    try:
                        p2p_status = pynvml.nvmlDeviceGetP2PStatus(
                            handle_a, handle_b, pynvml.NVML_P2P_CAPABILITY_ACCESS
                        )
                        link_type = "NVLink" if "NVLink" in str(p2p_status) else "PCIe"
                    except pynvml.NVMLError:
                        link_type = "PCIe"

                    # Estimate bandwidth
                    try:
                        pci_link_gen = pynvml.nvmlDeviceGetMaxPcieLinkGeneration(
                            handle_a
                        )
                        pci_link_width = pynvml.nvmlDeviceGetMaxPcieLinkWidth(handle_a)
                        # PCIe gen bandwidth per lane: Gen3=1GB/s, Gen4=2GB/s, Gen5=4GB/s
                        bw_per_lane = {
                            1: 0.25e9,
                            2: 0.5e9,
                            3: 1e9,
                            4: 2e9,
                            5: 4e9,
                            6: 8e9,
                        }
                        bw = bw_per_lane.get(pci_link_gen, 1e9) * pci_link_width
                    except Exception:
                        bw = 32e9  # Assume PCIe Gen4 x16

                    link = TopologyLink(
                        from_device_id=dev_a.device_id,
                        to_device_id=dev_b.device_id,
                        link_type=link_type,
                        bandwidth_bps=int(bw),
                        latency_ns=500 if link_type == "NVLink" else 1000,
                    )
                    # Store on both devices
                    dev_a.status.topology = link
                    dev_b.status.topology = link
                except Exception:
                    continue
    except Exception as exc:
        log.debug("Topology discovery incomplete: %s", exc)


# ────────────────────────────────────────────────────────────
# Vendor-agnostic fallback discovery
# ────────────────────────────────────────────────────────────


def discover_amd_devices() -> list[Device]:
    """Discover AMD GPU devices via ROCm SMI or AMD SMI."""
    # AMD is transitioning from rocm-smi to amd-smi.
    # This provides the interface contract; real implementation
    # waits for hardware access.
    #
    # Interface contract:
    #   - Parse `rocm-smi --showalljson` or `amd-smi static --json`
    #   - Extract GPU UUID, VRAM, driver version, topology
    #   - Map to Device(device_type=DeviceType.ROCM, device_class=DEVICE_CLASS_AMD_ROCM)
    log.debug("AMD ROCm discovery not yet implemented — interface contract defined")
    return []


def discover_qualcomm_devices() -> list[Device]:
    """Discover Qualcomm AI Engine / NPU devices."""
    # Qualcomm QNN SDK provides device detection for Snapdragon X Elite.
    # This provides the interface contract.
    #
    # Interface contract:
    #   - Check for QNN SDK via environment (QNN_SDK_ROOT, QNN_HTP_ARCH)
    #   - Enumerate HTP (Hexagon Tensor Processor) cores
    #   - Map to Device(device_type=DeviceType.QNN, device_class=DEVICE_CLASS_QUALCOMM_QNN)
    log.debug("Qualcomm QNN discovery not yet implemented — interface contract defined")
    return []


def discover_apple_devices() -> list[Device]:
    """Discover Apple Silicon GPU / Neural Engine devices."""
    # Interface contract:
    #   - Detect `arm64` + `Darwin` → Apple Silicon
    #   - Query Metal device count, unified memory, GPU family
    #   - Map to Device(device_type=DeviceType.METAL, device_class=DEVICE_CLASS_APPLE_METAL)
    log.debug("Apple Metal discovery not yet implemented — interface contract defined")
    return []


def discover_remote_devices() -> list[Device]:
    """Discover remote compute / API endpoints."""
    # Remote devices are registered by the Remote Compute Provider
    # via the NKI RegisterDevice method, not discovered locally.
    return []


# ────────────────────────────────────────────────────────────
# Unified discovery entry point
# ────────────────────────────────────────────────────────────


def discover_all_devices() -> list[Device]:
    """
    Run all device discovery backends and return a unified device list.

    This is the main entry point for hardware discovery. It runs each
    vendor backend independently — failure in one backend does not
    affect others. All devices are returned with stable IDs suitable
    for NKI registration.
    """
    all_devices: list[Device] = []
    backends = [
        ("CPU", discover_cpu_devices),
        ("NVIDIA", discover_nvidia_devices),
        ("AMD", discover_amd_devices),
        ("Qualcomm", discover_qualcomm_devices),
        ("Apple", discover_apple_devices),
        ("Remote", discover_remote_devices),
    ]

    for name, discover_fn in backends:
        try:
            found = discover_fn()
            if found:
                log.info("Discovered %d %s device(s)", len(found), name)
                all_devices.extend(found)
        except Exception as exc:
            log.warning("%s device discovery failed: %s", name, exc)

    if not all_devices:
        log.warning("No devices discovered — registering fallback CPU device")
        all_devices.append(_basic_cpu_device())

    return all_devices


def build_resource_slices(devices: list[Device]) -> list[ResourceSlice]:
    """Convert discovered devices into ResourceSlices for the scheduler."""
    slices = []
    for device in devices:
        if not device.status.phase.is_operational:
            continue
        slice_ = ResourceSlice(
            slice_id=f"slice-{device.device_id}",
            device_id=device.device_id,
            device_class=device.device_class.to_string(),
            node_id=platform.node(),
            capacity=device.spec.total_resources,
            available=device.status.available,
            attributes={
                "vendor": device.spec.vendor,
                "model": device.spec.model,
                "architecture": device.spec.architecture,
                "device_type": device.spec.device_type.name,
                "compute_units": device.spec.compute_units,
                "capabilities": list(device.spec.capabilities),
            },
            health_score=1.0 if device.status.is_healthy() else 0.5,
        )
        slices.append(slice_)
    return slices


__all__ = [
    "discover_all_devices",
    "discover_cpu_devices",
    "discover_nvidia_devices",
    "discover_amd_devices",
    "discover_qualcomm_devices",
    "discover_apple_devices",
    "discover_remote_devices",
    "build_resource_slices",
]

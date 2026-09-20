# RFC-0006: Device ABI v1

- **Status:** Draft
- **Date:** 2026-08-04
- **Depends on:** RFC-0001, RFC-0002

## Problem

Hardware devices (CPU, CUDA, ROCm, Vulkan, NPU, etc.) are currently probed ad-hoc with no stable interface, no topology discovery, no driver lifecycle management, and no health monitoring.

## Proposed Contract

Device ABI v1 defines 14 operations: discover, probe, verify, bind, initialize, allocate, free, submit, synchronize, reset, suspend, resume, unbind, health, telemetry, topology.

See `spec/device-abi/v1/device_abi.proto`.

## Key Decisions

1. **Process isolation** — Drivers run in `nous-driverd`, never linked into `nousd`
2. **Topology graph** — PCIe/NVLink/RDMA/NUMA links between devices recorded
3. **Memory types** — Device (VRAM), Host (pinned RAM), Unified, KV Cache pools
4. **Health monitoring** — Temperature, power, utilization, memory errors
5. **Power management** — Suspend/resume for energy efficiency

## Backend Priorities

Tier 1: CPU, CUDA
Tier 2: ROCm, Vulkan, OpenVINO
Tier 3: Metal, SYCL, CANN, QNN, DSP, FPGA, NPU

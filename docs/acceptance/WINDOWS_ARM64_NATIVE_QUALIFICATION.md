# Windows ARM64 Native Qualification

Qualification date: 2026-09-21

This record covers source-level qualification of APEIR on one Windows ARM64
host. It is not an official ARM64 binary release qualification and does not
change `runtime-components.lock.json`, whose published artifacts remain
Windows x86_64.

## Revisions and host

| Item | Observed value | Status |
| --- | --- | --- |
| Distribution branch | `feature/reality-execution-arm64` | PASS |
| Distribution baseline | `09d3ff7b907dbe7e464373d397ff494098464d1c` | PASS |
| Kernel revision | `b7b3244f72e6c7c6f87ad2c3f713d13df2b5c267` | PASS |
| Distribution lock revision | `b7b3244f72e6c7c6f87ad2c3f713d13df2b5c267` | PASS |
| Host OS | Windows 10 Enterprise, build 19045 | PASS |
| Physical architecture | ARM64, Qualcomm ARMv8, 8 logical CPUs | PASS |
| Interactive PowerShell process | x86 under Windows ARM emulation | PASS |
| Python | 3.12.10, native ARM64, 64-bit | PASS |
| Python executable | `%LOCALAPPDATA%\Programs\Python\Python312-arm64\python.exe` | PASS |
| Rust host | `aarch64-pc-windows-msvc` | PASS |
| Kernel target | `aarch64-pc-windows-msvc` | PASS |

The PowerShell process architecture is recorded separately from the Python
and Rust process architectures. x86 emulation was not accepted as native
ARM64 evidence.

## Qualification results

| Qualification item | Status | Evidence |
| --- | --- | --- |
| Distribution source install | FAIL | The requested `.[tier1,dev,a2a,mcp]` install did not complete; the core plus `dev` editable install completed and supports the tested Node paths. |
| Kernel native build | PASS | Repository `bootstrap.ps1` and `build.ps1` completed with the installed ARM64 MSVC toolset. |
| Kernel PE architecture | PASS | `apeird.exe`, `nous-provider-worker.exe`, and `apeir-kernelctl.exe` report PE machine `0xAA64`. |
| Kernel startup | PASS | Native `apeird` reached the local NKI endpoint with the reference worker. |
| NKI | PASS | `apeir-kernelctl doctor` reported Kernel state `READY`. |
| Reference workload | PASS | The deterministic reference backend produced a receipt and committed journal state. |
| Kernel inspect | PASS | Inspect reported no active operations and no corrupted sequences. |
| Node identity | PASS | Ed25519-backed node identity remained stable across restart. |
| Resource discovery | PASS | Host OS, architecture, CPU, memory, storage, network, USB, and COM facts were read from the host. |
| Execution host inventory | PASS | Node status reports real tool paths, versions, availability, and physical I/O facts. |
| Execution preflight | PASS | Native ARM64 plus Python 3.12 and Cargo requirements returned `ELIGIBLE`; missing or mismatched facts return `INELIGIBLE` with reasons. |
| Local Relay lifecycle | PASS | Register, heartbeat, reconnect, control acknowledgement, redelivery, and trust persistence passed targeted tests. |
| Remote Relay | BLOCKED | No external Relay endpoint or credentials were supplied for this qualification. |
| Artifact | PASS | Verified artifact transfer, content-addressed commit, and ready acknowledgement passed targeted tests. |
| Restart/recovery | PASS | Kernel restarted against the same journal at sequence 8; Node heartbeat sequence and identity also recovered. |
| Clean Kernel shutdown | NOT_TESTED | The smoke runner terminates the daemon by exact PID to exercise restart recovery; no administrative shutdown command exists. |
| Sleep/resume | NOT_TESTED | A physical screen-off/sleep/resume cycle was not performed during this run. |
| Multi-hour soak | NOT_TESTED | The long-running entry point was prepared but was not left running for several hours during qualification. |

Runtime evidence is generated beneath `.local/evidence/` and is deliberately
Git-ignored. The canonical rerun command is:

```powershell
.\scripts\arm64\smoke-arm64-node.ps1
```

## Execution Host v1 facts

The qualified host reported these tools as available:

| Tool | Version |
| --- | --- |
| Git | 2.47.1.windows.1 |
| Python | 3.12.10 |
| pip | 26.2.1 |
| rustc | 1.97.1 |
| Cargo | 1.97.1 |
| Node.js | 24.16.0 |
| npm | 11.13.0 |

The following were truthfully reported unavailable: CMake, Ninja, Docker,
Podman, esptool, `idf.py`, OpenOCD, and `kicad-cli`.

Windows SetupAPI probing found present USB root-hub and composite device
identifiers without exposing device serial numbers. No active COM port and no
Python serial module were detected, so serial availability is `false`; USB
presence is not treated as authorization to access a device.

Execution Host inventory describes only `what exists`. Every inventory and
preflight result carries `authority: none` and `grants_capabilities: false`.
Existing APEIR Capability, Policy, Admission, and Kernel paths remain the only
authorization boundary.

## Long-running node mode

Run the native Node in the foreground so Ctrl+C remains an explicit lifecycle
boundary:

```powershell
.\scripts\arm64\run-arm64-node.ps1
```

The Node stores identity, heartbeat sequence, status, resource snapshots, tool
availability, and telemetry below `.local/arm64-node/`. Inventory probes are
cached for five minutes while heartbeats continue at the configured interval.
A Relay URL and its public identity may be supplied to the script when a real
Relay environment is available.

## Known limitations

- The Tier 1 aggregate dependency set is not qualified on this host. The first
  installation attempt failed while resolving/building ARM64 heavy dependencies.
- The ARM64 `cryptography`, `rpds`, and `websockets` extension imports emitted
  Windows first-chance illegal-instruction diagnostics on this Snapdragon host;
  targeted tests still exited successfully. This requires dependency-level
  compatibility investigation before release qualification.
- CMake/Ninja, container runtimes, embedded toolchains, active COM ports, and
  Python serial support are absent.
- No external Relay, sleep/resume cycle, or multi-hour soak was available.
- Kernel binaries are local debug builds. No staging, SHA-256 publication, or
  ARM64 release lock was created.

## Targeted verification

- `tests/platform/test_detector.py`: 13 passed.
- `tests/node_runtime/test_node_service.py` plus
  `tests/node_runtime/test_execution_host.py`: 22 passed.
- `tests/node_runtime/test_node_protocol.py`: 8 passed.
- `scripts/arm64/smoke-arm64-node.ps1`: PASS.

The next direct Reality Execution step is a physical sleep/resume and multi-hour
soak with a configured external Relay, followed by installation of the serial
toolchain and a real USB/COM execution preflight.

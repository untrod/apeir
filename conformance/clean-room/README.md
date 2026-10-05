# Clean-Room Extension Tests

## Current acceptance scope

M3.6 validates Python SDK wheel installation and public Distribution contract
consumers using existing governed simulation. See the
[Developer Platform audit](../../docs/development/DEVELOPER_PLATFORM.md).
The native NKI/ABI scenarios below are qualification plans, not claimed passes.
Other language SDK availability must be checked before selecting an example.

## Purpose

Prove that a third party can build a working Nous Provider using ONLY public
specifications and the Provider SDK — without reading kernel internals.

## Rules

### Allowed
- `spec/public-api/v1beta1/` — all public specifications
- `sdk/provider/python/` — public Python Provider SDK
- `sdk/python/` and `sdk/c/include/` — existing public NKI/C surfaces
- `conformance/clean-room/examples/` — clean-room examples
- `nous-ctk` CLI — conformance test kit
- Public documentation

### Forbidden
- Reading `kernel/crates/*` source code
- Reading `kernel/daemons/nousd/src/*` source code
- Importing `nous_runtime.kernel.*` private modules
- Direct access to nousd journal/SQLite
- Modifying kernel code
- Bypassing NKI for Kernel-managed operations
- Bypassing Governance or Distributed Work admission for Reality operations

## Test Cases

### Test 1: Remote Model Provider
Build a Provider that registers a remote LLM API (OpenAI-compatible) as an
Engine, registers it via NKI, and executes a Chat workload through it.

### Test 2: CPU/ONNX Execution Provider
Build a Provider that discovers a local CPU, registers it as a Device,
loads an ONNX model, and executes an inference workload.

### Test 3: Virtual Hardware Device Provider
Build a Provider that simulates a hardware device (e.g., a mock GPU),
registers it with proper DeviceSpec/DeviceStatus, reports telemetry,
and handles allocation/deallocation.

### Test 4: Scheduler Policy Plugin
Build a WASM Component that implements a custom scheduling policy,
registers it with the kernel, and influences placement decisions.

### Test 5: Minimal Distribution
Build a complete Nous Distribution that selects a kernel version,
includes providers and models, configures policies, and builds
a signed distributable package.

## Success Criteria

For each test:
- [ ] Runs against a real nousd instance
- [ ] Passes `nous-ctk run --level DISCOVERABLE`
- [ ] No kernel code modified
- [ ] No private Python modules imported
- [ ] No direct journal access
- [ ] All communication via NKI or stable Provider ABI

## Reference examples

The repository currently contains `examples/remote-model/provider.py` and
`examples/cpu-onnx/provider.py`. They are native qualification examples, not M3.6
acceptance evidence. Virtual-device, scheduler-plugin, minimal-distribution and
additional language SDK references remain future work. Do not infer results from
an example's presence or an unconfigured CTK declaration.

# Clean-Room Extension Test — RC7

## Purpose

Prove that a third party can build a working Nous Provider using ONLY public
specifications and the Provider SDK — without reading kernel internals.

## Rules

### Allowed
- `spec/public-api/v1beta1/` — all public specifications
- `sdk/provider/` — Provider SDK (Rust, Python, TypeScript, C, WIT)
- `conformance/clean-room/examples/` — clean-room examples
- `nous-ctk` CLI — conformance test kit
- Public documentation

### Forbidden
- Reading `kernel/crates/*` source code
- Reading `kernel/daemons/nousd/src/*` source code
- Importing `nous_runtime.kernel.*` private modules
- Direct access to nousd journal/SQLite
- Modifying kernel code
- Bypassing NKI for any operation

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

## Directory Structure

```
conformance/clean-room/
├── README.md              ← this file
├── rules.md               ← detailed rules for testers
├── examples/              ← allowed reference examples
│   ├── remote-model/      ← Test 1 reference
│   ├── cpu-onnx/          ← Test 2 reference
│   ├── virtual-device/    ← Test 3 reference
│   ├── scheduler-plugin/  ← Test 4 reference
│   └── minimal-distro/    ← Test 5 reference
├── results/               ← test result artifacts
└── audit/                 ← audit scripts
```

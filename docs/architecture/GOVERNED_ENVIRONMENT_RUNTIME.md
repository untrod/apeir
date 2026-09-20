# Governed Environment Runtime

Status: P18 integrated-host implementation (2026-09-01)

## Purpose

The Environment Runtime gives Nous a typed, governed execution boundary for
local sandboxed processes and OCI containers. It extends the existing Runtime,
Kernel sandbox, governance, EventStream, Workspace, and ArtifactRegistry. It
does not introduce a second scheduler, policy engine, event history, or artifact
store.

## Ownership

- The model may propose an environment or command.
- Runtime validates the contract, checks compatibility, and owns lifecycle.
- Governance authorizes every state-changing API operation.
- The existing Kernel `ProcessSandbox` applies local process limits.
- Providers translate the validated contract into host-specific execution.
- EventStream is the only lifecycle history.
- ArtifactRegistry records bounded command evidence and outputs.
- Desktop is an inspector and control surface over the authenticated API.

## Stable contracts

`ExecutionEnvironment` uses schema `nous.environment/v1`. Provider negotiation
uses `nous.environment-provider/v1`. The compatibility handshake also checks
the product, Kernel, NKI, API, and event schema versions before the service is
made available.

The environment contract bounds provider, type, image, architecture, OS, CPU,
memory, GPU, network, filesystem, devices, mounts, lifetime, task, run, trace,
state, and provider handle. Unknown fields are rejected. Callers cannot forge
state, provider handles, timestamps, or error state. Persisted records carry a
canonical SHA-256 digest and fail closed on tampering.

Default policy is:

- no network;
- read-only root filesystem;
- no device or GPU access;
- no host mounts;
- bounded CPU, memory, process count, output, and lifetime;
- argv execution only, with no shell string or inline secret environment data.

## Providers

### LocalSandboxProvider

The local provider reuses the existing Windows `ProcessSandbox` and Job Object
integration. Each environment receives a dedicated scratch directory below
`.nous/environments/workdirs`. Host workspace mounts and HTTP allow-list claims
are rejected because this provider cannot provide a filesystem namespace or a
hard network namespace on the current Windows 10 host.

Its evidence level is `integrated-host`, not container isolation. The API and
Desktop report `hard_network_isolation=false` and
`filesystem_namespace_isolation=false` instead of overstating containment.

### OCIContainerProvider

The OCI provider is engine-neutral at the contract boundary and can translate
to Docker or Podman. Its generated container policy includes no network,
read-only root, dropped capabilities, no-new-privileges, a non-root user,
bounded PIDs/memory/CPU, and a no-exec temporary filesystem. It never enables
privileged mode, host PID/network, container-engine sockets, implicit host
volumes, devices, or GPU access.

Explicit mounts remain bounded by the contract. HTTP allowlists fail closed
until a governed egress proxy exists. On the current reference host neither
Docker nor Podman is installed, so OCI evidence is static contract/security
evidence only; no Linux-container execution claim is made.

## Lifecycle and evidence

The lifecycle is `created -> preparing -> ready -> running -> ready`, with
explicit suspended, stopping, stopped, destroyed, and failed states where
allowed. Create, start, run, stop, and destroy are persisted atomically. A
non-zero command or timeout fails the run and retains evidence while returning
a healthy provider to `ready`; provider cleanup failures place the environment
in `failed`.

Each run writes a bounded JSON result below
`artifacts/environments/<environment>/<run>.json`, registers it as an Artifact,
and emits canonical environment/run events. Restart recovery reloads and
digest-verifies environment records.

## API and Desktop

Authenticated routes under `/api/v1/environments` expose status, inventory,
records, logs, and governed create/start/run/stop/destroy mutations. Mutation
proposals are bound to required capabilities such as `runtime.execute`,
workspace read/write, network HTTP, GPU, or device access.

The Desktop Environment Inspector exposes provider availability, security
defaults, resources, lifetime, explicit mounts, lifecycle actions, argv JSON,
one-use approval retry, logs, and Artifact output. It displays explicit warnings
for partial local isolation and an unavailable OCI engine.

## Acceptance boundary

P18 Environment Runtime foundation has passed its focused tests, full
Runtime/Desktop/Tauri regression, security scan, packaged Windows build, and
native API approval/lifecycle replay for the Windows 10 x64 integrated-host
scope. Linux-container acceptance remains open until Docker or Podman is
explicitly installed/configured and a real isolated container is exercised on
this host.

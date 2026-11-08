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

The local provider delegates to `ProcessSandbox`; it has no ordinary host
process fallback. Each environment receives a scratch directory below
`.nous/environments/workdirs`. Host mounts, device/GPU passthrough and HTTP
allowlists remain rejected.

Windows requires its existing disposable Windows Sandbox backend. An optional
Linux x86-64 adapter accepts an operator-provisioned, digest-pinned QEMU profile
and the exact Python interpreter in that profile. It copies one authorized
project into a read-only guest snapshot, provides no network device or live
host mount, and runs the child as UID 1000 with bounded resources. Authenticated
guest messages belong to one invocation; they are process receipts, not
independent business-effect verification.

Linux commands must explicitly select `read_only_workspace: true`. The default
write-capable command remains unchanged and fails closed on this read-only
backend. Other executables, guest stdin, third-party Python packages and general
write-back are outside this profile. Provider probes expose that scope; a
configured environment alone is not a successful command.

The [Linux provisioning instructions](../operations/deployment/DEPLOYMENT.md#read-only-python-test-vm)
describe trusted inputs and the real-process probe. No profile is downloaded or
enabled by a model, layout, extension or API request. The APEIR Rust Kernel and
its component lock are unchanged.

### OCIContainerProvider

The OCI provider is engine-neutral at the contract boundary and can translate
to Docker or Podman. Its generated container policy includes no network,
read-only root, dropped capabilities, no-new-privileges, a non-root user,
bounded PIDs/memory/CPU, and a no-exec temporary filesystem. It never enables
privileged mode, host PID/network, container-engine sockets, implicit host
volumes, devices, or GPU access.

Explicit mounts remain bounded by the contract. HTTP allowlists fail closed
until a governed egress proxy exists. An installed Docker/Podman CLI alone does
not qualify an execution backend; current probe evidence must establish its
isolation. The Linux VM qualification does not certify ordinary containers.

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

Historical P18 foundation evidence remains in Engineering Review; it does not
qualify a current native installer. The Linux read-only VM has separate dated
execution and rejection evidence. Broader process profiles, native Windows 10
installation and physical-device effects retain their own gates.

# Nous Runtime 2.0 Architecture

## Purpose

Nous Runtime provides one authoritative execution environment for tasks, model
calls, governance, memory, artifacts, devices, and long-running work. Clients
control the Runtime through stable interfaces; they do not own parallel state.

## Layer model

```text
CLI / Desktop / SDK / Device Clients
                 |
        Control Plane and API
                 |
      Governance and Authorization
                 |
            Runtime Kernel
       /          |           \
    Tasks       Models       Knowledge
       \          |           /
        Events / State / Artifacts
                 |
     Providers / Nodes / Local Systems
```

## State ownership

| State | Authoritative owner |
| --- | --- |
| Runtime and workspace | `nous_runtime.kernel` and workspace services |
| Tasks and checkpoints | task, scheduler, execution, and checkpoint modules |
| Models and providers | model gateway, registry, resolver, router, scheduler |
| Permissions and approvals | governance and security modules |
| Events, traces, and metrics | event, trace, and monitoring modules |
| Artifacts and evidence | artifact, evidence, and verification modules |
| Retrieval and memory | retrieval, context, experience, and project modules |

A module may request a state change through an owner interface. It must not
mutate another subsystem's storage directly.

## Execution path

1. A client submits an intent or task through the CLI, SDK, Desktop, or API.
2. The Runtime creates or resolves the execution context.
3. Governance evaluates identity, permission, approval, and risk requirements.
4. Planning and routing select capabilities, providers, models, nodes, and
   fallback policy.
5. Execution emits standard events, traces, metrics, checkpoints, and artifacts.
6. Verification evaluates the result and records evidence.
7. The authoritative stores persist the final state and recovery information.

## Model path

Business modules call the stable model gateway. Provider selection and response
normalization remain behind the gateway, resolver, router, scheduler, and
adapter layers. Provider credentials are references, not values copied into
business objects, events, or logs.

## Control surfaces

- CLI: operational and diagnostic interface.
- HTTP API: versioned control-plane contract.
- Desktop: optional Tauri/React client.
- SDK: programmatic client and extension interfaces.
- Nodes and devices: protocol-driven remote execution surfaces.

The Desktop and remote clients are optional. The core Runtime starts without a
GUI, remote provider, or network connection.

## Compatibility

Pre-versioned API aliases and selected legacy bridges remain for existing
callers. New code must use the current kernel, gateway, governance, and event
contracts. Compatibility policy is documented under
[`docs/development/`](../development/README.md).

## Extension rules

- Reuse the existing state, event, error, credential, trace, and metrics models.
- Keep optional integrations optional.
- Declare capabilities and permissions before execution.
- Preserve cancellation, timeout, retry, fallback, and audit behavior.
- Add tests for every public behavior or compatibility path.
# Developer setup

Follow [CONTRIBUTING](../../CONTRIBUTING.md) for source setup, branch policy and
standard checks. Read the [canonical architecture](../architecture/README.md)
and [milestone status](../../ROADMAP.md) before adding a subsystem.

`nous_runtime` contains the Distribution services. `desktop` is the optional
Tauri/React client. Third-party Providers use the [public SDK](DEVELOPER_PLATFORM.md)
and [Provider guide](PROVIDER_DEVELOPMENT.md), rather than internal Runtime imports.
The independently released Rust Kernel is pinned by the root component lock;
Python compatibility modules are not a second native Kernel.

[Runtime module reference](RUNTIME_MODULE_MAP.md) is navigation, not authority.
For Controller and Node setup use the [operations runbook](../operations/compute-mesh/OPERATIONS.md).

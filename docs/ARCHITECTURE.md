# Architecture

APEIR consists of two independently released projects: APEIR Kernel and APEIR
Distribution. The Kernel owns authority; the Distribution owns user experience,
orchestration, and integrations.

```text
Desktop / CLI / SDK
        |
Authenticated Runtime API
        |
Policy and cost preflight
        |
Kernel Client over NKI
        |
APEIR Kernel: admit -> permit -> lease -> execute -> receipt
        |
Provider worker / governed backend
```

The Distribution never writes the Kernel journal and cannot create permits or
leases. Unsupported NKI versions and unavailable Kernel services fail closed.
The old `nous_runtime.kernel` Python namespace contains migration-only data
models and import shims; it is not a trusted execution authority.

Start with [the architecture index](architecture/README.md),
[the execution path](architecture/EXECUTION_PATH.md), and
[the security boundary](architecture/SECURITY_BOUNDARY.md).

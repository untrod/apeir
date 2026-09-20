# APEIR Distribution boundary

APEIR Distribution is the installable product around the independently released
APEIR Kernel. It contains the desktop application, Runtime API, CLI, SDKs,
Provider workers, extension adapters, and node/deployment services.

## Authority

The Rust Kernel is authoritative for admission, permits, resource leases,
durable execution state, effects, and execution proof. Product operations reach
that authority only through the Kernel Client and NKI. The Distribution may
prepare requests and present results, but it may not synthesize Kernel state.

## Compatibility

`nous_runtime`, `nous` command aliases, `NOUS_*` variables, and `nous.*.v1`
protocol identifiers remain during the migration window. They do not represent
a second product or a second Kernel.

## Local state

Databases, logs, credentials, caches, downloaded models, artifacts, and evidence
are user data. They are created at runtime and excluded from public source and
source archives.

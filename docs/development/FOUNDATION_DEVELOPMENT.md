# Foundation development workflows

## Kernel

Build and test the Rust workspace in `kernel`. A change to a frozen contract
requires compatibility fixtures for the previous version. Internal refactoring
must remain behind NKI or an ABI.

## Provider

Implement only the public Provider SDK and NPA interfaces. Run the provider-v1
conformance suite and a clean-room example. Providers may execute delegated work,
but they cannot own workload state, commit effects or persist credentials.

```text
nous ctk list
nous ctk run --suite provider-sdk --level DISCOVERABLE
nous registry list
```

## Micro

Compile `micro/src/nous_micro.c` with the target toolchain and run the host
reference test first. Zephyr consumes the portable source as a module. FreeRTOS
ports must use the same ABI and keep the safety callback mandatory.

## Distribution

A distribution selects signed kernel, provider and model artifacts. It does not
fork contract semantics. Record target architecture, contract versions, hashes,
toolchain and validation level in the build manifest.

```text
nous distro init <name> --dir <workspace>
nous distro validate --dir <workspace>/<name>
nous distro test --dir <workspace>/<name>
```

## Validation levels

- Static: schema, lint or compile only.
- Simulated: deterministic host test or fault injection.
- Integrated: multiple real processes on one host.
- Hardware: named target device and toolchain.
- Field: representative deployment with recorded evidence.

Reports must use the highest level actually demonstrated; planned hardware work
is not reported as validated.

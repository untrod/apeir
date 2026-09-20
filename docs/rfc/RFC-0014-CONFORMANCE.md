# RFC-0014: Conformance Test Kit

- **Status:** Draft | **Depends on:** RFC-0001, RFC-0004, RFC-0005, RFC-0006

## Purpose

The Conformance Test Kit (CTK) verifies that third-party engines, devices, and clients correctly implement the Nous ABI without requiring access to kernel source code.

## Test Categories

1. **NKI Contract Tests** — Every NKI method has a contract test. Request → expected response shape.
2. **Engine ABI Tests** — Engine adapter passes all 17 operations with correct types.
3. **Device ABI Tests** — Device adapter passes all 14 operations with correct types.
4. **State Recovery Tests** — Fault injection: crash, corrupt, partition → recover correctly.
5. **Resource Tests** — Admission control, lease grant/expiry/renewal, backpressure.
6. **Security Tests** — Default-deny, capability enforcement, isolation verification.
7. **Cross-Platform Tests** — Linux x86_64, Linux ARM64, Windows x86_64, Windows ARM64.
8. **Migration Tests** — Old format → new format → round-trip preserves data.
9. **Benchmark Tests** — Performance regression detection against baseline.

## Running

```bash
# Run all conformance tests
nous-ctk run --target engine --adapter ./my_engine_adapter.so

# Run specific category
nous-ctk run --category security --target kernel

# Generate conformance report
nous-ctk report --format json --output conformance.json
```

## Certification

Engines/devices passing all CTK tests receive a conformance badge and are listed in the Nous-compatible registry. Test results are reproducible and versioned.

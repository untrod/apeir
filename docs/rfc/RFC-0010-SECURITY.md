# RFC-0010: Security Kernel

- **Status:** Draft | **Depends on:** RFC-0001

## Trusted Computing Base

TCB = nousd + nous-types + nous-state + nous-resource + nous-security + nous-nki + journal + minimal crypto (ed25519, SHA-256).

Everything else runs in isolated processes.

## Default-Deny

All 9 conditions must be met before executing side-effect work:
1. Authenticated Principal
2. Explicit Capability Grant
3. Validated WorkloadSpec
4. Active ResourceLease
5. Valid Deadline
6. Cancellation Policy
7. Governance Decision
8. Isolation Profile
9. Audit ID

## Capability Manifest

Explicit declaration: reads, writes, devices, network_destinations, credentials, side_effects, reversibility, data_classification, requires_approval, resource_limits.

No guessing risk from capability name strings.

## Process Isolation

- Linux: cgroup v2, namespaces, seccomp, LSM, read-only fs, IOMMU, network egress
- Windows: Job Object, Restricted Token, AppContainer, Named Pipe ACL, filesystem ACL, Firewall

## Supply Chain

Model import: Download→Hash→Signature→License→SBOM→Format→Tensor Shape→Memory Bound→Operator Check→Isolated Conversion→Smoke Test→Benchmark→Quarantine/Admit.

Blocked by default: pickle, trust_remote_code, unsigned binaries, unknown operators.

See `kernel/crates/nous-security/src/lib.rs` for implementation.

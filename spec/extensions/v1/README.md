# Nous Extension IR v1

`nous.extension.json` is the normalized, vendor-neutral description produced by
Nous compatibility adapters. It is not an execution permit.

Supported import surfaces in v1:

- Agent Skills `SKILL.md` directories and ZIP archives;
- Nous native manifests;
- legacy Nous JSON skills, plugins, and both historical Pack shapes;
- OpenAPI 3 documents;
- MCP client configuration declarations.

Every imported capability is only a request. Installation records
`authority: none`; activation and code execution must be admitted by NKI and the
authoritative Kernel. Adapters must never install dependencies, start a process,
connect to a network, or evaluate package code while inspecting an extension.

Compatibility levels are independent from trust:

- C0 discover;
- C1 validate;
- C2 import;
- C3 governed execution;
- C4 round-trip interoperability;
- C5 certified and reproducible.

The JSON Schema in this directory is the interchange contract. Runtime
dataclasses may enforce additional semantic constraints.

`extension-operation-receipt.schema.json` describes the persisted C3 execution
evidence. The receipt stores identities, capability and policy bindings,
timestamps and digests, but deliberately excludes raw operation inputs,
credentials and output content. An atomic operation claim prevents the same
idempotency key from invoking an adapter twice; an interrupted claim remains
indeterminate and fails closed for operator review.

`extension-export-report.schema.json` describes the C4 machine-readable loss
report. Exported Agent Skills never carry Kernel grants. Fields that the target
format cannot express are listed explicitly, and every re-import begins with
`authority: none`.

`extension-provenance.schema.json` and `extension-signature.schema.json`
describe the C5 evidence stored beside each immutable package. Installation
also generates a standards-valid CycloneDX 1.6 `bom.json`. The registry and
lock bind the original content, normalized IR, SBOM, provenance and detached
signature record. Kernel admission receives those verified digests but no
source instructions, secret values or private signing material.

Signature status is intentionally not a trusted boolean: `Unsigned`, `Signed`,
`Verified`, `Invalid`, and `Unknown` are distinct states. Admission accepts
only locally verified evidence whose signature state is `Unsigned` or
cryptographically `Verified`; all malformed, unknown and invalid states fail
closed. The v1 detached-blob envelope supports local Ed25519 now and reserves
provider identifiers for future Sigstore/Cosign integration.

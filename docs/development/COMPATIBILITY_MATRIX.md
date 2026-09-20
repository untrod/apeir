# Compatibility Matrix

This matrix separates declared support from evidence collected on the current
release-maintenance device.

## Python

| Version | Project metadata | Current local evidence |
| --- | --- | --- |
| 3.10 | Supported | Remote CI required |
| 3.11 | Supported | Remote CI required |
| 3.12 | Supported | 2,452 tests passed on 3.12.10 ARM64 |
| 3.13+ | Not declared | C3 targeted tests run on local Python 3.14; not full-version certification |

## Platforms

| Platform | Status | Evidence |
| --- | --- | --- |
| Windows 10 x64 | C3 execution + C5 supply-chain subset validated locally | Rust Kernel/NKI, governed extension execution, disposable VM isolation, real protocol paths and Kernel-bound extension evidence validated on 2026-09-05 |
| Windows 10 ARM64 | Previously validated | Runtime, CLI, Wheel, and Desktop web build evidence; not rerun in this phase |
| Linux x64/ARM64 | CI target | Must pass remote CI and packaging gates |
| macOS | CI target | Must pass remote CI and packaging gates |
| ARMv7 Lite | Limited target | Lite-node tests and device validation required |

## Optional components

| Component | Requirement |
| --- | --- |
| Cloud providers | Provider credential and network access |
| Local models | Compatible local runtime, model files, RAM, and optional accelerator |
| ChromaDB | Optional vector retrieval dependency |
| FastEmbed | Optional embedding dependency |
| Desktop web build | Node.js and npm |
| Native Desktop package | Rust, Cargo, Tauri, and platform build tools |
| Installer GUI | Optional PySide6 dependency |

## Extension formats

Compatibility is assigned per execution surface, not merely per imported file
format. `C2` means normalized import only; it does not grant authority.

| Surface | Level | Governed execution evidence | Current limitation |
| --- | --- | --- | --- |
| OpenAPI 3 GET/HEAD/POST over HTTPS | C3 subset | Kernel admission, approval, parameter-bound permit, WebGateway policy, response validation and receipt | Unsupported methods and unmappable operations fail closed |
| MCP remote HTTPS via official Python SDK v2 | C3 subset | Discovery and invocation use Kernel permits/receipts plus session-pinned public IP, TLS/SNI verification, exact origin/path, no redirects and bounded uncompressed responses | Real third-party endpoint interoperability remains release-matrix work |
| MCP stdio | C3 on Windows 10 x64 | Official SDK client and server run together inside the network-disabled Windows Sandbox VM; permit stays on the host | Other operating systems require their own strong-backend certification |
| Agent Skills / `SKILL.md` | C2 | Import, normalization, integrity and admission are implemented | Code/process execution is disabled without a strong sandbox |
| Nous native and legacy plugin/pack formats | C2 | Import, normalization, integrity and admission are implemented | No direct legacy executor; availability of a VM does not certify all formats |

## C4 round-trip and C5 supply-chain scope

| Surface | Current status | Boundary |
| --- | --- | --- |
| Agent Skills and Nous legacy JSON skills | C4 export/re-import | Semantic comparison and machine-readable loss report; authority is always reset to none |
| Nous plugin and Runtime/Kernel Pack formats | C4 export/re-import | Target-format losses are explicit; no Kernel grant is exportable |
| OpenAPI 3 | C4 restricted round-trip | Original supported OpenAPI document can round-trip; arbitrary Nous tools are rejected as unmappable |
| MCP configuration | C4 redacted round-trip | Only credential reference names survive; credential values never export or install |
| A2A 1.0 | C4 protocol interoperability | Official SDK task, streaming, artifact and error lifecycle; remote pinned HTTPS is restricted to exact authorized origin |
| Installed extension evidence | C5 supported subset | CycloneDX 1.6 SBOM, provenance, five-state detached signature model, tamper checks, secret rejection and Kernel-visible verified digests |

C5 applies to packages accepted by the current v1 inspectors and registry. It
does not certify every third-party ecosystem format, arbitrary remote service,
or non-Windows process sandbox. Sigstore/Cosign attestation and transparency-log
verification remain future interoperability work; local Ed25519 detached-blob
verification is implemented now.

The C3 Gate is **achieved for the validated Windows 10 x64 subset**. This is a
platform-scoped claim, not certification of every package metadata target.

On the current Windows 10 x64 host (2026-09-05), all eight real Windows Sandbox
boundary/resource/cleanup tests pass. Official MCP stdio runs in the VM, the
real Rust Kernel-to-VM path passes, the official Streamable HTTP protocol passes
through pinned HTTPS transport, and invalid TLS is rejected. Governed callers
never fall back to Job Objects or a plain host process. Without a strong backend
they fail before process creation with `STRICT_SANDBOX_UNAVAILABLE`.

The certification threat model trusts the host OS and current local user; the
extension/guest is untrusted. Authorized execution is not a claim that an
arbitrary business result is true: receipts label protocol/schema validation
separately from independent verification. Real third-party endpoint breadth
remains release interoperability work rather than a C3 safety blocker.
Generated validation reports are distributed with the matching release
artifact rather than retained in the source repository.

A platform is not considered release-validated solely because it appears in
package metadata. Release evidence must record the operating system,
architecture, Python version, dependency set, and executed gates.

# Public release checklist

Target: **APEIR Distribution 0.1.0-rc1**

A checked item must be supported by output produced from the exact source and
artifacts being released. Earlier development reports are not release evidence.

## Source baseline

- [x] Public source is extracted without old Git metadata.
- [x] Databases, logs, caches, credentials, binaries, and local evidence are excluded.
- [x] Public branding uses APEIR while v1 compatibility identifiers remain stable.
- [ ] The maintainer has reviewed and committed the final source tree.

## Kernel integration

- [x] Kernel repository revision and Windows x64 binary hashes are pinned.
- [x] Production model execution fails closed when NKI is unavailable.
- [x] Unsupported NKI versions are rejected.
- [x] The old Python Runtime authority is reduced to a compatibility shim.
- [x] Final capability evidence distinguishes NKI/Kernel workloads from bounded
  Runtime-service effects and prevents false Kernel traversal claims.

## Desktop and capabilities

- [x] Native `APEIR.exe` build completes from a clean source candidate.
- [x] Start, crash, port-conflict, shutdown, and orphan-process tests pass.
- [x] File, process, document, network, model, MCP/Skill, denial, timeout,
  cancellation, receipt, and audit cases pass on Windows 10 x64.

## Packaging and supply chain

- [x] NSIS installer and portable ZIP are built and smoke-tested.
- [x] Install, upgrade, launch, uninstall, and cleanup tests pass.
- [x] Secret scan, license review, SBOM, and checksums pass.
- [ ] Windows Defender scan passes on a host where Defender is enabled.
- [ ] Release binaries and provenance are signed by the maintainer.

## Publication

- [ ] Known limitations and the test matrix match the final evidence.
- [ ] The maintainer approves the final diff, tag, upload, and release notes.

Do not call the candidate released until every unchecked release-blocking item is
closed or explicitly documented as outside the rc1 support claim.

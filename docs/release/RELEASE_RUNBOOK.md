# Release runbook

This runbook creates APEIR Distribution `0.1.0-rc1`. Publication and signing
require the maintainer's credentials and explicit approval.

## 1. Freeze inputs

1. Work from a clean Distribution checkout.
2. Confirm `runtime-components.lock.json` points to a public APEIR Kernel commit.
3. Download or build the exact locked Kernel artifacts and verify their SHA-256.
4. Confirm every version manifest reports `0.1.0-rc1`.

## 2. Verify source

```powershell
python -m ruff check nous_runtime tests scripts integrations sdk
python -m pytest -q
python scripts/security_scan.py
python scripts/markdown_link_check.py .
```

## 3. Verify desktop

```powershell
cd desktop
npm ci
npm run lint
npm test
npm run typecheck
npm run build
cd ..
```

## 4. Build Windows artifacts

```powershell
$env:APEIR_KERNEL_ROOT = (Resolve-Path "..\apeir-kernel").Path
.\scripts\build-windows-x64-launcher.ps1 -KernelRoot $env:APEIR_KERNEL_ROOT
```

Run install, upgrade, launch, shutdown, uninstall, orphan-process, and Windows
Defender checks on Windows 10 x64. Store generated evidence outside the source
tree.

## 5. Produce release metadata

Generate a source manifest, SHA-256 files, CycloneDX SBOM, dependency-license
report, and provenance statement. Verify all files from a second clean directory.

## 6. Sign and publish

After maintainer approval, sign the installer, executable, checksums, and
provenance with the project's release identity. Create the annotated tag and
GitHub release only after signature verification succeeds.

## Rollback

Do not replace a published artifact in place. Withdraw the affected release,
document the reason, correct the source, and publish a new candidate version.

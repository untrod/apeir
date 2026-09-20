# Release Process v1.0

## Pipeline

```
Source Commit (main)
  ↓
CI: python -m pytest tests/          <- Must pass
  ↓
CI: python -c 'compileall...'        <- Must pass
  ↓
CI: grep -r "sk-" . --include="*.py" <- Must be empty
  ↓
Build: pip install build && build    <- Create wheel + sdist
  ↓
Checksum: sha256sum dist/*           <- Generate checksums
  ↓
SBOM: pip-audit / syft               <- Generate SBOM
  ↓
Artifact Attestation                 <- Sign with cosign (optional)
  ↓
Release Candidate Tag: v1.0.0-rcN
  ↓
Manual: Clean-machine E2E test
  ↓
Release Tag: v1.0.0
```

## Artifacts

| Artifact | Tool | Required |
|----------|------|:--------:|
| Source tarball | `python -m build` | Yes |
| Wheel | `python -m build` | Yes |
| Checksums | `sha256sum` | Yes |
| SBOM | `syft` or `pip-audit` | Yes |
| Attestation | `cosign` | Optional |

## Release Checklist

- [ ] All tests pass: `python -m pytest tests/ -q`
- [ ] No secrets: `grep -r "sk-" . --include="*.py"` is empty
- [ ] Demo mode works: `NOUS_DEMO_MODE=1 nous start`
- [ ] Version matches: `nous version` == tag
- [ ] CHANGELOG updated
- [ ] Release notes written
- [ ] Git tag signed

## Versioning

SemVer: `MAJOR.MINOR.PATCH`
- MAJOR: Breaking API changes
- MINOR: New features (backward-compatible)
- PATCH: Bug fixes

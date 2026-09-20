# Artifact Policy v1.0

## Principle

Every release artifact must be traceable to its source revision.

## Artifacts Produced

| Artifact | Format | Purpose |
|----------|--------|---------|
| Source distribution | `.tar.gz` | pip install from source |
| Wheel | `.whl` | pip install binary |
| Checksum file | `.sha256` | Integrity verification |
| SBOM | `.spdx.json` | Dependency inventory |

## Integrity

```bash
# Verify checksum
sha256sum -c nous_runtime-1.0.0.tar.gz.sha256

# Inspect SBOM
cat nous_runtime-1.0.0.spdx.json | python -m json.tool
```

## Artifact Traceability

```
git rev-parse HEAD  ->  included in artifact metadata
git tag v1.0.0      ->  matches version in pyproject.toml
```

## Storage

- Artifacts stored alongside GitHub Release
- Checksums published in release notes
- SBOM attached to release

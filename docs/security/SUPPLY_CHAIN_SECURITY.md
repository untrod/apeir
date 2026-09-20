# Supply Chain Security v1.0

## Dependencies

| Category | Tool | Status |
|----------|------|:------:|
| Dependency audit | `pip-audit` | Recommended |
| SBOM generation | `syft` or `pip-audit` | Recommended |
| License check | `pip-licenses` | Recommended |
| Code scanning | GitHub CodeQL | Optional |
| Secret scanning | GitHub secret scanning | Enabled |

## SBOM

Software Bill of Materials lists all dependencies with versions and licenses. Generated at release time:

```bash
pip install pip-audit
pip-audit -r requirements.txt --format json > sbom.json
```

## Artifact Integrity

```bash
# Build
python -m build

# Checksum
sha256sum dist/* > dist/checksums.sha256

# Verify
sha256sum -c dist/checksums.sha256
```

## Signed Releases (Optional)

```bash
git tag -s v1.0.0 -m "Nous Runtime v1.0.0"
```

## CI/CD Integration (GitHub Actions plan)

```yaml
# .github/workflows/release.yml
- name: Run tests
  run: python -m pytest tests/ -q
- name: Secret scan
  run: grep -r "sk-" . --include="*.py" && exit 1 || true
- name: Build
  run: python -m build
- name: Generate SBOM
  run: pip-audit --format json > sbom.json
- name: Upload artifacts
  uses: actions/upload-artifact
```

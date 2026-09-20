# Release Checklist

**Version:** 0.1.0a0

## Pre-Release

- [ ] All tests pass (`pytest tests/`)
- [ ] Security scan: HIGH = 0
- [ ] MEDIUM findings triaged
- [ ] Ruff lint clean
- [ ] `compileall` passes
- [ ] `git diff --check` clean
- [ ] Wheel builds (`python -m build`)
- [ ] Clean install verified
- [ ] `nous init` works
- [ ] `nous doctor` passes
- [ ] `nous demo` works
- [ ] `nous status` works
- [ ] `nous shell` launches
- [ ] Server smoke test passes
- [ ] Node smoke test passes
- [ ] Local E2E controlled agent test passes
- [ ] API routes respond correctly

## Documentation

- [ ] README.md current
- [ ] CHANGELOG.md updated
- [ ] ROADMAP.md updated
- [ ] ALPHA_SCOPE.md accurate
- [ ] KNOWN_LIMITATIONS.md current
- [ ] OPEN_SOURCE_READINESS_AUDIT.md complete
- [ ] Architecture docs current
- [ ] Deployment docs current

## Hygiene

- [ ] No secrets in tracked files
- [ ] No personal information
- [ ] No proprietary tool names
- [ ] No development-assistant attribution
- [ ] Third-party licenses present
- [ ] `.gitignore` covers temporary files

## Release

- [ ] Version bumped in `nous_runtime/version.py`
- [ ] Version bumped in `pyproject.toml`
- [ ] Tag created (`v0.1.0a0`)
- [ ] Wheel uploaded to PyPI (maintainer decision)
- [ ] Release notes published

## Post-Release

- [ ] Verify `pip install nous-runtime` works
- [ ] Verify quick start instructions
- [ ] Monitor for issues

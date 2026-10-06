# Contributing to APEIR

Read the [constitution and invariants](docs/architecture/DISTRIBUTION.md),
[architecture owners](docs/architecture/README.md), [milestone status](ROADMAP.md)
and [security policy](SECURITY.md) before changing execution or authority.
Audit existing implementation and tests; prefer extending canonical owners over
adding parallel systems. Open an RFC for broad boundary changes.

## Branch and acceptance policy

`main` is the only permanent development branch. Start one coherent Gate from
current main using `feature/`, `fix/`, `docs/`, `security/`, `provider/`,
`platform/`, `hardware/` or `research/`. Milestone examples are in ROADMAP.
No permanent develop or archive branch is needed: immutable tags and Git history
retain accepted evidence. Branch names describe work, not models/tools.

Integrate by PR with passing required CI and resolved conversations. Use a
normal merge when preserving acceptance SHAs; never squash/rebase accepted
history, force-push published history or move published tags. Delete a completed
branch only after all commits are reachable from main and no unresolved PR work
or unpublished acceptance evidence remains. Single-maintainer PRs need no
mandatory reviewer approval or unproven commit-signing requirement.

Kernel is frozen at `87fd1b2ff28ef14ab1a515a58162592b452fda2e`. Do not change it
or the component lock to bypass an unavailable native binary. Report a genuinely
impossible external contract for explicit authorization.

## Development and validation

```bash
python -m venv .venv
# Activate for your shell
python -m pip install -e ".[dev,a2a,mcp,scientific]"
python -m ruff check nous_runtime tests scripts integrations sdk
# Check formatting on changed Python files; do not reformat unrelated baselines.
python -m ruff format --check path/to/changed.py
python -m compileall -q nous_runtime sdk/provider/python
python -m pytest -q
python scripts/document_hygiene_audit.py
python scripts/markdown_link_check.py
python scripts/comment_quality_audit.py
python scripts/repository_identity_audit.py
python scripts/git_metadata_audit.py
python scripts/security_scan.py
python scripts/ci/verify_release_versions.py
python -m pytest -q tests/repository/test_kernel_component_lock.py
python scripts/ci/verify_kernel_components.py --repo-root .
git diff --check
```

Run directly affected contracts, integration, recovery and negative-security
regressions before full tests. For the optional real OCI reference follow
[Provider conformance](docs/architecture/PROVIDER_CONTRACT.md); use fake credentials.
Development requires an executable trusted CPython base interpreter, a writable
checkout and per-test temporary storage, a resolvable hostname and named user.
Containers running process lifecycle tests must use `--init` (or a proven
equivalent reaper); bare PID 1 may retain orphan zombies. Keep HOME unchanged:
desktop persistence tests use the existing `NOUS_WORKSPACE_ROOT` configuration,
and daemon tests pass an explicit workspace. See
[supported environment qualification](docs/development/DEVELOPER_PLATFORM.md#supported-development-environment)
for the measured distinction between configured and unsupported environments.
Run Desktop lint/tests/typecheck/build when affected. Record exact counts,
platforms, dependency/provider availability, skipped items and baseline failures.
A missing native binary means the hash verifier is BLOCKED, even when its contract
tests pass. Do not weaken assertions, skip failures or invent physical success.

## Completing work

Update canonical docs and status rather than creating competing summaries.
Use semantic Conventional Commits (for example `fix(recovery): reconcile lost
responses`). Push, verify CI and local/remote SHA agreement, and leave a clean
worktree. Each Gate's report distinguishes exercised acceptance from prepared
contracts, simulation, hardware pending and environmental blockers.

Never commit secrets, private prompts, local runtime databases, logs or generated
binaries. Preserve backward compatibility where it does not violate security
invariants. Report vulnerabilities privately under SECURITY, not public issues.
Release publication requires its separate [runbook](docs/acceptance/RELEASE_RUNBOOK.md)
and maintainer approval; checkpoint tags are not production releases.

# Coding agent entry point

Read [architectural invariants](docs/architecture/DISTRIBUTION.md) first, then
[canonical architecture](docs/architecture/README.md) and the current
[roadmap/status](ROADMAP.md). Follow [CONTRIBUTING](CONTRIBUTING.md) for branches,
validation and PRs; [SECURITY](SECURITY.md) covers disclosure.

- Audit existing code, contracts, tests and evidence before implementing. Reuse
  authoritative paths; do not add second Work, Workflow, Capability, Artifact,
  Verification, Agent, execution or authorization systems.
- Preserve authority separation and fail-closed UNKNOWN behavior. Models,
  planners, schedulers, graphs, Nodes and Providers cannot grant themselves
  authority. Reconcile uncertain effects; never blindly replay them.
- Keep Kernel frozen at `87fd1b2ff28ef14ab1a515a58162592b452fda2e` unless explicitly
  authorized. If an external contract is impossible, stop and report evidence.
- Use fake credentials in Cloud. Never publish secrets or runtime state. Never
  claim physical validation from simulation, host contracts or prepared code.
- Distinguish reproducible baseline failures from new regressions. Preserve
  failure evidence; do not skip or weaken a check merely to obtain PASS.
- Work on one milestone-sized branch from main. Finish authorized semantic work
  with appropriate tests, standard checks, documentation, a semantic commit,
  push and CI verification. Verify local/remote HEAD agreement and clean worktree.
  Integration uses a PR and preserves acceptance SHAs; never force-push or move
  published milestone tags. Retire branches only after reachability/PR checks.

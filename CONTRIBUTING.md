# Contributing to APEIR

Thank you for helping improve APEIR. Focused fixes, tests, provider
adapters, platform validation, documentation, and security hardening are
welcome.

## Before you begin

- Search existing issues and pull requests.
- Open an issue or RFC before broad architecture work.
- Keep Server Runtime ownership authoritative; do not create parallel task,
  model, approval, credential, workspace, or event stores.
- Never commit credentials, local Runtime state, databases, private prompts,
  conversation logs, personal paths, or generated test output.

## Development setup

```bash
python -m venv .venv
# Activate the environment for your shell
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

Run the relevant tests while developing, then run the release gates before
requesting review:

```bash
python -m ruff check nous_runtime tests scripts integrations sdk
pytest
apeir doctor
apeir status
apeir models doctor
npm --prefix desktop ci
npm --prefix desktop run build
```

Changes that affect optional integrations should document which dependencies,
providers, platforms, and network conditions were tested.

## Change design

- Preserve public interfaces or provide a documented compatibility path.
- Use the standard APEIR error, event, trace, metrics, credential, and
  governance models.
- Keep optional GUI, model, vector, and provider dependencies optional.
- Add tests for new behavior and regressions; do not weaken existing assertions
  to make a change pass.
- Update user-facing documentation and `CHANGELOG.md` when behavior changes.

## Commits

New commits should follow Conventional Commits:

```text
fix(runtime): preserve checkpoint recovery state

docs(user): clarify offline model setup
```

Use `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, or `chore`
with an optional scope. Keep unrelated cleanup, behavior changes, and generated
evidence in separate commits. Do not rewrite published history.

## Branch naming

Branch names describe the work, not the tools used. Use these prefixes:

**Allowed:**
```text
feature/    — new capability or enhancement
fix/        — bug fix
refactor/   — code restructuring without behavior change
docs/       — documentation only
test/       — test additions or fixes
release/    — release preparation
experiment/ — short-lived exploration
kernel/     — kernel subsystem
provider/   — provider integration
platform/   — platform support (Windows, ARM64, etc.)
security/   — security fixes or hardening
archive/    — archived or bookmarked work
```

**Forbidden:**
```text
codex/*     claude/*     gpt/*       ai/*
agent-*     auto-*       chatgpt/*   copilot/*
```

Branch names must never reference AI tools, automation agents, or model names
used during development. The public repository represents work that maintainers
have reviewed, tested, and accepted responsibility for.

## Pull requests

A pull request should explain:

- the problem and scope;
- implementation and ownership boundaries;
- compatibility and migration impact;
- security and privacy impact;
- tests and platforms exercised;
- documentation changes and known limitations.

Maintainers review and merge changes. Release, governance, and approval controls
must not be bypassed for convenience.

## Security reports

Do not use a public issue or pull request for an undisclosed vulnerability.
Follow [SECURITY.md](SECURITY.md).

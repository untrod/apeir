# R6 laptop checkpoint

- Date: 2026-09-26
- Branch: `feature/reality-execution-v2`
- Distribution base: `94f1f7e676dc907fcb6c9a809355ed9103d1dee7`
- Kernel revision: `13d7bbb62cdb9aeb1da53d0aab4a1d7e8afc27f2`

## Purpose

This checkpoint preserves the verified R6 work completed on the Windows 10 x64
development host before the remaining end-to-end acceptance work. It is not an
R6 release declaration and does not replace the final regression gate.

## Status

| Gate | Status | Evidence or boundary |
| --- | --- | --- |
| R6 overall | **PARTIAL** | Closure work remains. |
| Provider structured-tool gate | **PASS** | A live provider completed the structured decision fixture. Credentials are not persisted in the repository. |
| Calculator Work fixture | **PASS** | Work planning, tool selection, execution, observation, and completion were exercised. |
| Files Runtime | **PASS** | Governed search, read, and patch paths have targeted coverage. |
| Persistent Shell | **PASS** | Start, status, output, attach, completion, timeout, and cancellation paths have targeted coverage. |
| Windows Sandbox | **PASS** | Strong-isolation unit coverage and real Windows Sandbox smoke coverage passed. |
| MCP isolation | **PASS** | The stdio bridge executes in strong isolation with an explicit read-only package path and no non-isolated fallback. |
| ItsDangerous code vertical | **INCOMPLETE** | APEIR has not yet completed the fixed issue end to end without human substitution. |
| Desktop reconnect | **NOT RUN** | Deferred until the code vertical passes. |
| Runtime forced-restart recovery | **PARTIAL** | Component-level recovery exists; the required end-to-end fault-injection run remains. |
| Context and token efficiency | **PARTIAL** | A failed-work baseline exists; a successful comparable Work baseline remains. |
| Full regression | **INTERRUPTED** | No authoritative final summary was produced. |

The most recent full-suite attempt reached approximately 50 percent with no
reported failures and two skips before the run was interrupted. An earlier
checkpoint observed approximately 48 percent with no reported failures before
the execution budget ended. Neither observation is a full-regression pass.

## Changes preserved by this checkpoint

### Provider and decision contract

- DeepSeek-compatible structured JSON responses use the supported response
  format without weakening schema validation.
- Provider configuration is resolved from the target workspace before the
  Runtime workspace fallback.
- Work decisions receive an explicit schema and a larger bounded output budget.
- Capability names and executable tool identifiers remain distinct; unknown
  tools continue to fail closed.

### Governed code work

- The legacy blocking command tool is excluded from Work execution.
- Persistent shell descriptions expose the governed allowlist and session
  lifecycle to the model.
- Mutation intent recognizes narrowly scoped requests while retaining workspace
  and policy checks.
- Tests cover provider payloads, credentials, tool discovery, decision parsing,
  file mutation intent, and persistent processes.

### Strong isolation

- Virtual-environment Python workloads use the trusted base interpreter with an
  explicit read-only package mapping instead of staging an entire environment.
- Workspace inputs remain snapshotted and writable outputs remain guarded by
  the existing commit checks.
- The MCP stdio bridge is standalone and uses isolated Python startup with an
  explicit package whitelist. It does not execute `.pth` files or use a local
  process fallback.

### Execution-host inventory

- Tool probes use a bounded, process-wide cache.
- Explicit refresh bypasses the cache.
- The first strong-isolation inventory probe remains a slow acceptance
  operation and is not part of the daily fast test lane.

## Verification performed

- Focused R6 suite: **110 passed, 3 deselected** in 280.32 seconds.
- Earlier focused integration suite: **92 passed** in 257.09 seconds.
- Real MCP stdio isolation smoke: **1 passed** in 104.41 seconds.
- Real execution-host inventory acceptance: **1 passed** in 622.69 seconds.
- ItsDangerous upstream project tests inside Windows Sandbox: **130 passed**.
- Ruff lint on all modified Python files: **passed**.
- Ruff formatting check after formatting: **passed**.
- Sensitive-information scan: **1,842 files scanned; 0 findings**.
- Git whitespace check: **passed** before this document was added.

Generated environments, test output, credentials, local evidence, and build
artifacts are not included in the checkpoint.

## Kernel boundary

The Kernel repository is unchanged at
`13d7bbb62cdb9aeb1da53d0aab4a1d7e8afc27f2`. This checkpoint does not alter
Permit, Lease, NKI, journal authority, policy authority, or Kernel state
machines.

## Remaining R6 closure order

1. Complete the fixed ItsDangerous task through WorkHarness, Files Runtime, and
   Persistent Shell without human repair.
2. Verify Desktop reconnect to the same durable background Work.
3. Verify forced Runtime restart, including unknown-effect recovery semantics.
4. Record the successful Work context and token baseline.
5. Complete the Research and Scientific vertical acceptances.
6. Run one final release-class regression and record its complete summary.

Until all six steps pass, the only valid project-level status is `R6 PARTIAL`.

# Verified Execution Demo

Follow the [Source Quick Start](../../docs/operations/getting-started/QUICK_START.md)
first. No API key, real hardware or optional AI dependencies are needed.
Run from the installed checkout, using a new empty directory for each scenario.

```bash
apeir demo --workspace ./demo-match --phase prepare --json
apeir demo --workspace ./demo-match --phase resume --approve-once --json
```

The first command observes firmware `1.0.0`, creates a deterministic Plan and
the original firmware Work, and pauses for human approval. The second command
is an explicit **local OS-user Approve Once** action; the planner cannot approve.
It resumes that Plan and Work, updates persisted simulated firmware to `2.0.0`,
receives the Node's OperationReceipt, submits a separate read Work, and commits
only after EffectVerification MATCH. This is not remote-human qualification.

For a single-command run, use `apeir demo --workspace ./demo-new --approve-once`.
Without `--approve-once`, it reports WAITING and zero mutation effects.

## Failure and recovery gallery

```bash
apeir demo --workspace ./demo-deny --scenario deny --json
apeir demo --workspace ./demo-mismatch --scenario mismatch --approve-once --json
apeir demo --workspace ./demo-unknown --scenario unknown --approve-once --json
apeir demo --workspace ./demo-response-loss --scenario lost-response --approve-once --json
apeir demo --workspace ./demo-restart --scenario restart --approve-once --json
```

| Scenario | Actual result | Mutation effects |
| --- | --- | --- |
| match | COMMITTED / MATCH, observed firmware 2.0.0 | 1 |
| deny | Original Work stays CREATED; durable denial, no mutation receipt | 0 |
| mismatch | VERIFIED / MISMATCH; target 3.0.0 differs from actual 2.0.0 | 1 |
| unknown | VERIFIED / UNKNOWN; stale post-effect Observation cannot establish success | 1 |
| lost-response | Before recovery: no Controller receipt; after persisted reconciliation and fresh observation: COMMITTED / MATCH | 1 total |
| restart | Components close/reopen after pause; original Work/Plan resumes to MATCH | 1 |

`prepare` and `resume` also demonstrate recovery across two separate CLI processes.
Starting again in a nonempty directory is rejected rather than overwriting evidence.
`lost-response` injects a real simulated effect followed by response loss, then
reopens persisted owners; it never issues a second mutation to obtain a receipt.
Do not delete or edit the state to force a successful result.

## Inspectable evidence

JSON is a projection of actual Runtime state, not a canned success response:
AgentSession/Plan/Workflow provenance, Distributed Work, device and Node IDs,
authorization/approval/grant audit, signed receipt, independent read Work outputs,
EffectVerification and CAS references/integrity checks. The `operations` field
comes from the existing OperationsPlane over the same owners. State remains under
the chosen directory's `.nous/` (Governance, Relay Work/CAS, Node ledger, Reality,
simulator and AgentSession stores); JSON may be redirected to a local evidence file.
Generated Node private keys and local databases must **never** be committed or
shared publicly. Redact identities and paths before filing a report.

Scope is always `simulated=true`, `runtime-service`, `kernel_traversed=false`.
This exercises the governed signed Controller/Node protocol on loopback with a
built-in bounded simulated handler. It does not validate arbitrary third-party
script isolation, native Kernel traversal, physical firmware flashing, remote
IdP identity, packaging or production release qualification.

Acceptance tests: `python -m pytest -q tests/reality/test_verified_preview.py`.
They cover positive/negative effects, five self-approval attempts, CAS/provenance,
lost-response reconciliation and a two-process persistent restart. See
[ROADMAP](../../ROADMAP.md) for hardware and release blockers.

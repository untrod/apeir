# Proof-Carrying Execution — v1alpha

> Status: v1alpha (experimental)
> Target: RC8
> Reference: CAVA (arXiv 2607.13716) — canonical action verification

## Concept

Governance and signing verify that a Provider/Distribution is trustworthy.
But they cannot prove that:

- The executed action IS the approved action
- Execution parameters were NOT substituted
- Actual effects match declared intent
- The trace has NOT been tampered with
- No duplicate side effects occurred after failure

Proof-Carrying Execution generates independently verifiable evidence that
binds the approval, the action, and the observed effects into a cryptographic
chain.

## ProofCarryingAction

```
ProofCarryingAction {
    // Identity
    action_id: UUIDv7,
    causal_parent: UUIDv7 | null,   // Previous action in causal chain

    // What was intended
    canonical_action: {
        action_type: string,         // e.g., "git.commit", "email.send"
        parameters: CanonicalJSON,   // Deterministic serialization
        parameter_digest: SHA256,
    },

    // Who authorized
    principal: PrincipalRef,
    capability: CapabilityGrant,
    policy_decision: {
        policy_id: string,
        decision: ALLOW | DENY | ASK_APPROVAL | ESCALATE,
        decision_digest: SHA256,
    },

    // Approval
    approval: {
        approver: string,            // Human or system
        approval_id: UUIDv7,
        approved_action_digest: SHA256,  // MUST match canonical_action digest
        approved_at_us: uint64,
        approval_signature: bytes,
    },

    // Input
    input_digest: SHA256,            // All inputs hashed
    input_schema: string,            // Schema for verification

    // Execution
    execution_environment: {
        sandbox_id: string,
        engine_id: string,
        isolation_level: string,
        environment_digest: SHA256,   // Hash of the sandbox config
    },

    // Effects
    effect_intent: {
        declared_side_effects: string[],
        reversibility: REVERSIBLE | IRREVERSIBLE,
        resource_impact: ResourceVector,
    },
    effect_receipt: {
        actual_side_effects: string[],
        actual_resource_consumed: ResourceVector,
        receipt_digest: SHA256,
    },

    // Output
    output_digest: SHA256,
    output_schema: string,

    // Evidence
    replay_descriptor: {
        replayable: bool,
        replay_instructions: string,  // How to independently verify
        required_state_digests: SHA256[],
    },
    attestation: bytes,               // Cryptographic signature over all above
}
```

## WorkloadCertificate

```
WorkloadCertificate {
    workload_id: UUIDv7,
    principal: PrincipalRef,
    program_revision: string,
    action_chain: ProofCarryingAction[],  // Ordered, causally linked
    models_used: [{ model_id, engine_id, device_id }],
    tools_used: [{ tool_id, invocation_count }],
    approvals: [{ approval_id, approver, action_digest }],
    data_egress: { destination, data_classification, bytes }[],
    verifications: [{ verifier_id, passed, evidence_digest }],
    failures_recovered: [{ action_id, failure_reason, recovery_action }],
    final_side_effects: string[],
    certificate_digest: SHA256,
    attestation: bytes,
}
```

## Separation of Concerns

```
Planner    → Can only PROPOSE actions (no execution credentials)
Policy     → Decides ALLOW/DENY/ESCALATE (no execution credentials)
Effector   → Holds actual credentials, executes ONLY approved actions
Recorder   → Writes immutable evidence (append-only, no delete)
Verifier   → Independently checks: action == approved, effect == declared
```

No single component can: propose, approve, AND execute the same action.

## Durable Speculative Execution

### PURE Phases (can speculate)

- Model inference (read-only, no external effects)
- Retrieval (read-only database queries)
- Static analysis, compilation checks, test plan generation
- Candidate answer generation
- Cache warming computations

### SIDE-EFFECT Phases (default: NO speculation)

- Email send, code commit, file delete
- Payment, account modification, content publish
- Device control, industrial actuator
- Configuration change, user notification

### Speculation Protocol

```
1. Speculate(phase) → produces CandidateState
   - Only PURE phases or explicitly allowlisted side-effect phases
2. ValidatePreconditions(candidate)
   - Check that all assumptions still hold
3. Governance(candidate)
   - Policy engine evaluates risk
4. if governance == COMMIT:
       Effector.execute(candidate)
       Recorder.record(ProofCarryingAction)
   else:
       Discard(candidate)
       // Optional: Rebase, Recompute, or Compensate
```

### Fault Recovery

```
On failure during speculation:
  → Discard speculative state (no side effects to undo)

On failure during COMMIT:
  → Compensate if possible (reverse action)
  → If irreversible: Quarantine, human intervention required
  → Record ProofCarryingAction with effect_receipt showing failure

On duplicate execution detection:
  → Idempotency key check
  → If already committed: return existing ProofCarryingAction
  → If in-flight: wait for outcome
```

## Verification Protocol

```
fn verify_certificate(certificate: WorkloadCertificate) → VerificationResult:
    1. Check certificate.attestation signature
    2. For each action in certificate.action_chain:
       a. Verify causal_parent links
       b. Verify approval.approved_action_digest == action.canonical_action.parameter_digest
       c. Verify action.attestation signature
       d. Verify input_digest matches declared inputs
       e. Verify output_digest matches declared outputs
       f. Verify effect_intent is consistent with effect_receipt
       g. Verify execution_environment matches sandbox policy
    3. Verify no duplicate side effects in chain
    4. Verify all failures have recovery actions
    5. Return { valid: bool, violations: Violation[] }
```

## Violation Types

```
INVALID_SIGNATURE          — Cryptographic attestation failed
APPROVAL_MISMATCH          — Executed action ≠ approved action
EFFECT_MISMATCH            — Actual effects ≠ declared effects
MISSING_APPROVAL           — Side-effect action without approval
DUPLICATE_EFFECT           — Same side effect executed twice
CAUSAL_CHAIN_BROKEN        — Parent action not found or invalid
SANDBOX_VIOLATION          — Execution environment doesn't match policy
REPLAY_FAILED              — Independent verification couldn't reproduce
```

## Performance Budget

| Operation | Target Overhead |
|-----------|----------------|
| Action hashing + signature | < 1ms per action |
| Certificate generation | < 100ms per workload |
| Certificate verification | < 500ms per workload |
| Certificate storage | < 10KB per action |
| Replay verification | < 2x original execution time |

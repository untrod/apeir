# Execution contract

The normative contracts are the [Execution Path](EXECUTION_PATH.md),
[Runtime Coordination](RUNTIME_COORDINATION.md),
[State Ownership and failure semantics](STATE_OWNERSHIP.md) and
[Security Contract](SECURITY_CONTRACT.md).

Goal and Plan are proposals compiled into the existing durable Workflow. Its
handlers admit existing Work/Operation through Governance and the selected
execution scope. Placement is not authorization. A Provider callback is an
execution boundary, not an Agent-facing approval shortcut.

The earlier illustrative task YAML and direct `provider.invoke` pseudocode are
not an alternative execution API. In particular, a generic retry count cannot
justify replaying an uncertain state mutation. Reconcile the original operation's
persisted delivery/receipt evidence and independently observe the resource;
only MATCH establishes a verified effect.

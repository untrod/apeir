# Control Center Alignment

CLI, Desktop, Web and mobile surfaces use the same authoritative runtime stores
and execution contracts. The [Control Plane specification](CONTROL_CENTER_SPEC.md)
is authoritative for state projections, trusted remote human authentication,
governed controls and realtime transitions.

| Surface | Existing path | Authority |
| --- | --- | --- |
| Local CLI | Existing Governance CLI owner attestation and runtime lifecycle | Governance Gate only. |
| Desktop | Shared Operations Console plus existing API bridge/service bearer | Service authentication does not establish a human approver. |
| Web/mobile | Same Operations Console/API, external OIDC proof and protected human session | Existing Gate and explicitly enrolled permission rules. |
| Providers, Nodes, planners | Existing Work and Provider contracts | Cannot grant or approve their own authority. |

There is no console-owned job manager, capability registry, verification service,
Artifact store or audit ledger. Browser state is a disposable view. Changes are
admitted by existing Governance and applied through original lifecycle paths.
Scheduler placement does not grant authority; an execution host is a Node, while
a Device is a managed resource. Receipts describe execution evidence, while
independent observations establish effects. UNKNOWN remains fail-closed and
uncertain effects are reconciled rather than replayed.

Legacy `brain.py` and older mobile approval prototypes are compatibility paths,
not the trusted remote-human boundary. Historical v1 plans describing them as
the future Control Center are superseded by the current specification above.

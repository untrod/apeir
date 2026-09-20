# OpenClaw adapter

OpenClaw is an optional product-layer adapter. It is not part of the Nous trusted
computing base and owns no kernel state. The adapter may translate OpenClaw
sessions, nodes, schedules, and skills into NKI requests; execution, state,
credentials, effects, scheduling, and safety remain authoritative in `nousd`.

Local session tracking is a UI or compatibility cache only. It must never be
treated as evidence that a workload ran or an external effect committed.

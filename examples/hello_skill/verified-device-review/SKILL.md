---
name: verified-device-review
version: 1.0.0
description: Inspect governed simulated firmware evidence before proposing a change.
required_capabilities: [device.state.read, device.firmware.update]
suggested_tools: [skill_load]
tags: [simulation, evidence, review]
risk: high
verification: [fresh independent observation, EffectVerification MATCH]
---

Read the original Work, target and firmware observation. A requested capability
is not permission. Ask the Runtime to pause any firmware mutation for explicit
human approval; never approve it yourself. A receipt alone does not establish
the effect. Reconcile persisted evidence when the response is lost, acquire a
fresh independent observation and accept only MATCH. UNKNOWN and MISMATCH must
remain uncommitted. These instructions contain no executable scripts.

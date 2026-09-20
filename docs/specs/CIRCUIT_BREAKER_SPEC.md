# Circuit Breaker Spec

Nous is an Open Intelligence Runtime.

## States

- **CLOSED** — Normal operation, all traffic allowed
- **OPEN** — Circuit tripped, no traffic allowed, cooldown timer active
- **HALF_OPEN** — Probing with limited traffic after cooldown
- **FORCED_OPEN** — Manually opened, requires explicit trusted close
- **DISABLED** — Breaker bypassed

## Transitions

| From | To | Condition |
|------|----|-----------|
| CLOSED | OPEN | consecutive_failures >= threshold OR failure_rate >= threshold OR timeout_rate >= threshold |
| OPEN | HALF_OPEN | cooldown expired |
| HALF_OPEN | CLOSED | half_open_successes >= threshold |
| HALF_OPEN | OPEN | any failure in HALF_OPEN |
| Any | FORCED_OPEN | explicit trusted control |
| FORCED_OPEN | CLOSED | explicit trusted control only |
| Any | DISABLED | explicit trusted control |

## Breaker Keys

- `"{provider_id}:*"` — provider-level breaker
- `"{provider_id}:{model_id}"` — model-level breaker

## Safety

- FORCED_OPEN can only be cleared by explicit trusted control
- Model output cannot modify breaker state
- Provider metadata cannot modify thresholds
- OPEN circuits receive no normal traffic
- HALF_OPEN circuits receive only bounded probe traffic

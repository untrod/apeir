# Retry Policy Spec

Nous is an Open Intelligence Runtime.

## Bounded Retries

- max_attempts, max_cumulative_delay, max_additional_cost, max_additional_tokens
- Exponential backoff with bounded jitter
- Retry-After header respected
- Deterministic test mode with clock injection

## Never Retried

Authentication failure, authorization failure, invalid user input, policy rejection, unsupported capability, exhausted budget, explicit cancellation, output validation failure.

## Side-Effect Safety

Non-idempotent operations without idempotency key are retried only for: timeout, connection, server error, rate limit (requests that likely never reached or weren't processed by the server).

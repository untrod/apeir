# Failure Classification Spec

Nous is an Open Intelligence Runtime.

## Categories

15 failure categories: authentication, authorization, rate_limit, timeout, connection, server_error, malformed_response, output_validation, capability_unsupported, user_input, policy_rejection, budget_exceeded, runtime_internal, cancelled, unknown.

## Non-Retryable

Authentication, authorization, user_input, policy_rejection, capability_unsupported, budget_exceeded, cancelled, output_validation are never retried.

## Classification Logic

Deterministic. No LLM. Inputs: HTTP status, provider error code, exception type, timeout phase, validation result.

## Attribution

- provider_attributable: bool — fault lies with the provider
- model_attributable: bool — fault lies with the model

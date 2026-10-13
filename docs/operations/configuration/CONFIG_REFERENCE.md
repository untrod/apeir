# Config Reference

## Version

- Canonical runtime version: `nous_runtime/_version.py`
- Python package: `pyproject.toml`
- Desktop package: `desktop/package.json`
- Tauri package: `desktop/src-tauri/tauri.conf.json`
- Rust package: `desktop/src-tauri/Cargo.toml`
- SDK package: `nous_runtime/sdk/package.json`

## Credentials

Credentials must be referenced through providers, environment variables, or the credential/vault layer. Do not write API keys, tokens, or secrets into config files, logs, events, or audit reports.

## Runtime

Workspace, API host/port, provider routing, model defaults, node identity, and approval policy should be read from the runtime config registry or compatibility adapters. Desktop must not maintain a conflicting source of truth.

## Cost controls

APEIR applies limits before a model request reaches the Kernel. Defaults can be
changed through `APEIR_MAX_INPUT_TOKENS`, `APEIR_MAX_OUTPUT_TOKENS`,
`APEIR_MAX_REQUEST_TOKENS`, `APEIR_MAX_DAILY_TOKENS`,
`APEIR_MAX_DAILY_COST_USD`, `APEIR_MAX_MODEL_ATTEMPTS`,
`APEIR_MAX_RETRY_TOKENS`, and `APEIR_MAX_RETRY_COST_USD`.

Provider prices are intentionally configuration data because vendors change
them independently of APEIR releases. Point `APEIR_MODEL_PRICING_FILE` to a
reviewed catalog using [`../../../config/model-pricing.example.json`](../../../config/model-pricing.example.json).
Use the actual configured Provider ID and routed Provider model as the catalog
key, `provider-id/model-id`; a model-only key remains compatible. Replace the
example's `null` rates with reviewed USD prices per million tokens. An explicit
zero is a configured price, while a missing or `null` rate is unknown. No price
is inferred from a model ranking or an observation's legacy zero.

The default daily/retry USD limits reject an unpriced request before dispatch.
To select token-only policy explicitly, set both `APEIR_MAX_DAILY_COST_USD=none`
and `APEIR_MAX_RETRY_COST_USD=none`; a per-request USD limit still requires known
pricing. For the existing foreground Runtime command on a POSIX shell:

```bash
# Reviewed pricing with the default monetary limits:
APEIR_MODEL_PRICING_FILE=/path/to/reviewed-model-pricing.json nous runtime-api start
# Explicit token-only policy; unpriced billing remains UNKNOWN:
APEIR_MAX_DAILY_COST_USD=none APEIR_MAX_RETRY_COST_USD=none nous runtime-api start
```

Set equivalent process environment variables before starting Desktop/Runtime on
other platforms. Restart Runtime after changing policy or pricing: the product
Gateway loads this configuration when constructed. Model registry configuration
and Model Lab rankings do not change accounting policy. The existing
`GET /api/v1/usage` endpoint reads the same local ledger and reports policy,
known/estimated counters, unknown billing and outstanding reservations.
Its policy projection reports `budget_mode` and pricing `configured`, `loaded`,
`status`, `model_entries` and `priced_models`. These describe loaded preflight
rates, not vendor invoice verification or guaranteed matching of every selected
model. No private pricing path or raw configuration error is returned.
Missing Provider usage/cost is `null`, with separate measurement labels; unknown
does not mean free. Credential values are never written to the usage database.

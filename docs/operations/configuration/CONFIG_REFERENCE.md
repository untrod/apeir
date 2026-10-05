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
Unknown prices still receive Token limits, but cost estimates remain zero until
a price is configured. Actual Provider usage is normalized and stored locally;
credential values are never written to the usage database.

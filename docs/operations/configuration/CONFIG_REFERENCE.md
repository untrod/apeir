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

## Context permission policy

`NOUS_PERMISSION_POLICY` is an explicit trusted-host startup setting for the
existing Governance PermissionEngine. Point it to an owner-only JSON file directly
under the active authority's `.nous` directory. File discovery, request bodies,
model proposals and permission-status queries never select or create authority.
With no setting, the existing gate stays unchanged and selected-file delivery
remains unconfigured/blocked. Restart Runtime when initially selecting a policy;
each later check reads the file again. Missing, expired, corrupt, linked,
foreign-owner or broadly readable/writable policy fails closed. This file-loader
qualification is POSIX only; it provides no native Windows fallback.

The document accepts `rules` (at most128 existing PermissionRule objects) and an
optional timezone-aware `expires_at`. Each rule has `subject`, `action`, `resource`,
optional `effect` (`allow`/`deny`) and scalar `context_equals`. Conditions require
present, exact-typed facts; an absent key or integer1 cannot satisfy null/true.
Rules are deny-by-default with explicit deny precedence. A file-backed engine
does not accept runtime `add` calls. Keep credentials out of policy files.

For one service's file-sharing policy, use its authenticated subject (default
`api-service`), explicit `context.read`/`product.chat` rules, `workspace.read` for
the selected Workspace and `context.transfer` for the exact recipient. Scope the
last two with `context_equals.relative_path` where appropriate. The Workspace
resource is `workspace:` plus SHA-256 of its resolved absolute path string. The
recipient resource appends `:provider:` plus SHA-256 of the compact, sorted-key
JSON `{provider_id,endpoint,transport}` of the actual Gateway recipient. Use the
configured endpoint/transport, not a model name or a private credential. Direct
and NKI transports differ; a changed reviewer/fallback recipient needs its own
explicit policy. Never copy broad wildcard permissions merely to make a demo run.

On a supported POSIX host, after preparing/reviewing that file and its scopes:

```bash
chmod 600 /path/to/workspace/.nous/permission-policy.json
NOUS_WORKSPACE_ROOT=/path/to/workspace \
NOUS_PERMISSION_POLICY=/path/to/workspace/.nous/permission-policy.json \
  nous runtime-api start
```

This configuration is policy input, not an execution grant, trusted human
session, credential lease or effect evidence. Existing Operation approval,
expiry/revocation, sandbox, budget, delivery and verification checks still apply.
`GET /api/v1/security/permissions` returns configuration metadata; its compatibility
descriptions have `granted=null`/UNKNOWN until a real authorization is evaluated.

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

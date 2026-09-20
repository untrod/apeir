# Provider Guide

Providers connect the unified model gateway to remote or local model services.
Business modules must not initialize provider SDKs directly.

## Configure a provider

```powershell
nous provider add
```

For a guided common-provider setup:

```powershell
nous provider quick
```

Inspect the resulting profile without sending a model request:

```powershell
nous provider list
nous provider show PROVIDER_ID
nous provider status
nous provider doctor
```

Use `nous provider ping` for endpoint reachability and `nous provider test` only
when a real model call is intended.

## Credential rules

- Store a credential reference, not the secret value, in provider profiles.
- Prefer environment variables or the Runtime credential provider.
- Never write keys to YAML exports, logs, events, traces, screenshots, or Git.
- Redact query strings and authorization headers in diagnostics.

## Adapter contract

A provider adapter converts the unified request into a provider-specific call
and converts the response back into the unified response model. Routing,
timeout, retry, fallback, cancellation, tracing, metrics, and error
normalization remain Runtime concerns.

Extension guidance is available in
[`docs/development/PROVIDER_DEVELOPMENT.md`](../../development/PROVIDER_DEVELOPMENT.md).
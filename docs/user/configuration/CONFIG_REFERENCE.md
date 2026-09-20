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

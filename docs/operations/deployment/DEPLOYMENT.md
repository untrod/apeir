# APEIR Runtime Deployment Guide

## Supported Platforms

| Platform | Architecture | Status |
|----------|-------------|--------|
| Windows 10/11 | x64 | Supported |
| Windows 10/11 | ARM64 | Supported (RC2) |
| Linux | x64, ARM64 | Supported |
| macOS | Apple Silicon, x64 | Planned |

## Windows ARM64 Desktop

### Prerequisites

- Windows 10 ARM64 or Windows 11 ARM64
- Visual Studio Build Tools 2022 with "Desktop development with C++"
- MSVC v143 ARM64 build tools
- Windows 10/11 SDK
- Node.js 20+
- Rust toolchain with `aarch64-pc-windows-msvc` target
- Python 3.10–3.12

### Build

```powershell
# Install Rust ARM64 target
rustup target add aarch64-pc-windows-msvc

# Install desktop dependencies
cd desktop
npm ci
npm run build

# Build ARM64 installer
npm run tauri:build:arm64
```

The NSIS installer is generated at `desktop/src-tauri/target/release/bundle/nsis/`.

### Verify

```powershell
nous doctor
nous models doctor
npm --prefix desktop run build
```

## Windows x64 Desktop

```powershell
cd desktop
npm ci
npm run build
npm run tauri:build
```

## Linux

### Python Runtime

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
nous doctor
```

### Desktop (experimental)

Requires webkit2gtk and Tauri system dependencies. See [Tauri prerequisites](https://v2.tauri.app/start/prerequisites/).

## Runtime Configuration

### Provider Credentials

Provider API keys are referenced by environment variable name, never stored in configuration files:

```bash
export OPENAI_API_KEY="sk-..."
export DEEPSEEK_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
```

Then configure:

```bash
nous provider add
```

### Model Configuration

```bash
nous models doctor
nous models list
nous models configure
```

## Workspace Structure

```
workspace/
├── nous.yaml          # Project configuration
├── models.yaml        # Model registry (optional)
├── data/              # Runtime data
├── packs/             # Installed packs
└── projects/          # Project artifacts
```

## Health Verification

```bash
# Full diagnostic
nous doctor

# Model subsystem
nous models doctor

# Runtime status
nous status

# Run demo (no API key required)
nous demo
```

## Production Deployment

For production deployments, review:

- [Security documentation](../../architecture/security/OVERVIEW.md)
- [Trust boundaries](../../architecture/security/TRUST_BOUNDARIES.md)
- [Known limitations](../../acceptance/KNOWN_LIMITATIONS.md)
- [Release checklist](../../acceptance/PUBLIC_RELEASE_CHECKLIST.md)

## Remote Human Trust qualification

This procedure qualifies M3.5-Q; the current status is in [ROADMAP](../../../ROADMAP.md).
Software tests with fake identities are preparation, not a deployed-human PASS.
Use the existing [Control Plane contract](../../architecture/CONTROL_CENTER_SPEC.md)
and [security boundary](../../architecture/SECURITY_CONTRACT.md#m35-remote-human-boundary).

1. Deploy the existing Operations Console and Runtime API behind a trusted HTTPS
   origin. Prefer same-origin routing of `/api/v1` to the existing controller;
   keep controller storage durable and host-owned. Do not trust forwarded headers
   as human identity. Remote API binding retains its existing TLS/private-transport
   restrictions, and the browser-facing response must use HTTPS for Secure cookies.
2. Register a public OIDC client with authorization-code flow and S256 PKCE,
   an exact callback URI that loads the Operations Console, and no client secret.
   Disable implicit/password grants. Obtain canonical HTTPS authorization/token/
   JWKS endpoints from the selected issuer's published metadata; token redirects
   are rejected. Configure the IdP to emit signed `sub`, `iss`, `aud`, `exp`, `iat`,
   `nonce`, recent `auth_time` and `amr`. The required method (default `mfa`) must
   be backed by actual configured authentication, never a fabricated claim mapper.
3. Enroll the exact nonsecret issuer subject ID, not a mutable email/display name,
   in host-owned `.nous/human-identity.json` under `NOUS_WORKSPACE_ROOT`. Use
   owner-only file permissions and a protected parent directory on POSIX. Windows
   file enrollment remains fail-closed until its ACL qualification is implemented;
   this procedure does not certify it. Example **nonsecret** configuration:

```json
{
  "issuer": "https://idp.example.test/realms/apeir",
  "client_id": "apeir-operations",
  "redirect_uri": "https://console.example.test/",
  "authorization_endpoint": "https://idp.example.test/realms/apeir/protocol/openid-connect/auth",
  "token_endpoint": "https://idp.example.test/realms/apeir/protocol/openid-connect/token",
  "jwks_uri": "https://idp.example.test/realms/apeir/protocol/openid-connect/certs",
  "subjects": ["REPLACE_WITH_ENROLLED_SUBJECT_ID"],
  "required_methods": ["mfa"],
  "permissions": []
}
```

4. Set `NOUS_CONTROL_ORIGINS` to the exact public HTTPS console origin(s), for
   example `["https://console.example.test"]`. No wildcards, credentials or URL
   paths. Authentication alone grants nothing: start with empty permissions, then
   enroll narrow existing PermissionRule entries for the intended resource. The
   human ID is `oidc:<first 16 hex characters of SHA256(issuer)>:<subject ID>`.
   Approve Once requires `governance.approve` **and** `control.approve_once`;
   Deny requires `governance.approve` and `control.deny`. Do not use blanket `*`
   subjects/resources or enroll agents/services as humans. File configuration is
   loaded on controller startup; restart to apply file enrollment/policy changes.
   Explicit session/grant/resource revocation retains its existing durable behavior.
5. An actual enrolled human signs in through the browser/mobile Console and
   checks the target Device, Capability, risk, original Work and expected effect
   before Approve Once. Record the unchanged AgentSession/Plan/Workflow/Work/
   Operation IDs, resulting scoped grant, human subject/session/context audit
   binding, existing Node receipt, independent Observation and MATCH. Use the
   simulated firmware environment first; its effect remains simulated. Do not
   capture cookies, codes, tokens, PKCE verifiers or IdP credentials in evidence.
6. Repeat Deny (no state mutation), expiry, session revocation/logout + restart,
   wrong/un-enrolled subject, method/issuer mismatch, CSRF/untrusted Origin,
   nonce replay, duplicate/stale/expired approval and resource/grant revocation.
   Reload must restore only the original unexpired session; Sign out must reject
   later requests. Reconcile an effect whose ACK was lost without another effect
   or credential resolution. Store sanitized acceptance evidence and exact test/
   deployment versions before changing the remote-human Gate to PASS.

Local `tests/control_plane/test_oidc_transport.py` exercises the actual Authlib
exchange and PyJWT JWKS validation over TLS with an ephemeral fake test CA. It
checks invalid nonce/issuer, service unavailability and refused token redirects.
TLS verification is enabled; these automated fake-account tests are not evidence
that a real remote human authenticated. No production private key or long-lived
credential belongs in source, prompts, artifacts or audit.

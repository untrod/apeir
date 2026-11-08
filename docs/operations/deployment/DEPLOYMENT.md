# APEIR Runtime Deployment Guide

Use [Quick Start](../getting-started/QUICK_START.md) for installation and first
startup. This page selects deployment references; the existing remote-human
qualification procedure below retains its separate security requirements.

## Supported Platforms

[Platform policy](../platform/PLATFORM_SUPPORT_POLICY.md) separates current
software CI, historical host evidence and native installation. A declared target
is not an installed-product qualification. [ROADMAP](../../../ROADMAP.md) owns
current status.

## Windows ARM64 Desktop

### Prerequisites

See [the ARM64 host boundary](WINDOWS_10_ARM64_LOCAL.md#native-arm64-boundary).
Current ARM64 CI checks metadata, not a native installer. A supported builder and
approved target-native Kernel components are required before native packaging.

### Build

Follow the [Release Runbook](../../acceptance/RELEASE_RUNBOOK.md) only when that
target's component and toolchain gates are satisfied. An unqualified
`tauri build` result does not establish a distributable ARM64 application.

### Verify

Keep the exact target, OS, component hashes and executed checks in its report.
Do not reuse x64 hashes or interpret emulation as native ARM64 acceptance.

## Windows x64 Desktop

The current unsigned Portable/NSIS package and SHA-256 are in
[Quick Start downloads](../getting-started/QUICK_START.md#download-metadata).
Use the [official launcher build and validation](WINDOWS_10_X64_LAUNCHER.md),
not a frontend-only Tauri command. Current Windows 10 installation remains PENDING.

## Linux

### Python Runtime

Follow [Developer Setup](../getting-started/QUICK_START.md#developer-setup),
then start from a dedicated project directory:

```bash
apeir --no-intelligence runtime-api start
```

Model-free service startup does not qualify untrusted project execution.
Missing strict isolation stays BLOCKED; there is no host Shell fallback.

### Read-only Python test VM

The optional Linux x86-64 `ProcessSandbox` profile runs a pinned CPython
interpreter and its standard library in a disposable QEMU guest. It supports
read-only project tests, not arbitrary host commands, installed third-party
packages, networking or file write-back. The guest kernel is a platform input;
this does not rebuild or alter APEIR Kernel.

An operator must supply trusted QEMU, matching Linux kernel/modules, static
BusyBox, firmware and QEMU data/libraries. The builder copies local inputs;
it does not download or install them. Keep the resulting profile outside
projects and protected from other users. It is an operator deployment input,
not something a model, Provider configuration or layout may select.

From the matching source checkout and its Python environment:

```bash
python -m scripts.ci.build_linux_vm_profile \
  --qemu "$QEMU" --kernel "$GUEST_KERNEL" \
  --guest-modules "$GUEST_MODULES" --busybox "$BUSYBOX" \
  --firmware "$FIRMWARE" --qemu-data "$QEMU_DATA" \
  --qemu-libraries "$QEMU_LIBRARIES" --output "$APEIR_VM_ROOT" \
  > vm-profile-build.json
```

These variables are absolute paths to reviewed local inputs. `GUEST_MODULES`
is the matching `/usr/lib/modules/<version>` directory. `APEIR_VM_ROOT` must
not exist yet; the builder refuses to replace a reviewed profile. It uses
the current interpreter, excludes site-packages and GUI modules, records all
input digests, and includes a dedicated virtio entropy device. The Q35 machine
provides reference timers for guest clock calibration; no KVM or privileged
container is required. Use its matching standard SeaBIOS firmware rather than
the firmware for QEMU's separate microvm machine.

After reviewing `profile.json` and the build record, set the two operator
variables to its absolute filename and exact SHA-256:

```bash
export APEIR_LINUX_VM_PROFILE="$APEIR_VM_ROOT/profile.json"
export APEIR_LINUX_VM_PROFILE_SHA256="<reviewed profile.json SHA-256>"
python -m scripts.ci.probe_linux_vm \
  --workspace /absolute/project --report linux-vm-qualification.json
```

The probe executes real guest code and preserves each result in an adjacent
JSONL file, including failed checks. It does not change the project or make a
failed unit test pass. A different Runtime guest controller requires rebuilding
and reviewing the profile. This builder does not provide a redistributable VM
image or qualify other toolchains.

In Developer Workbench, select the `python-unittest` profile and a directory
containing standard-library `unittest` tests. Environment commands can opt in
with `read_only_workspace: true`; write-capable commands retain their previous
semantics and remain BLOCKED on this read-only backend. Existing Governance
approval still applies. Results contain the actual exit code, bounded output
and the tested input snapshot digest; a file SHA match is not a test result.

### Desktop (experimental)

Source Studio can use a browser. Native Linux Desktop needs the
[Tauri system prerequisites](https://v2.tauri.app/start/prerequisites/) and its
own component, build and installation qualification; no general native PASS is
claimed here.

## Runtime Configuration

### Provider Credentials

Use [Models and Providers](../guides/PROVIDER_GUIDE.md). Configure credential
references through the supported backend. Do not copy real keys into guides,
ordinary config, logs or browser storage.

### Model Configuration

Saving a Provider, authentication and actual inference are separate checks.
Cloud/local coexistence is covered in software; real services, model capabilities
and authorized inference budgets require their own qualification.

## Workspace Structure

Use an explicitly selected project root. The Runtime creates its owned state;
do not copy another workspace's identity, approvals or credentials into it.
[State ownership](../../architecture/STATE_OWNERSHIP.md) defines authoritative
records; layouts and UI caches do not replace them.

## Health Verification

In a second activated shell from the same project:

```bash
apeir runtime-api status --json
```

Use the [first verified simulated execution](../getting-started/QUICK_START.md#first-verified-execution)
to inspect original Work, approval, receipt and independent simulated observation.
A health response alone proves neither inference nor a device effect.

## Production Deployment

Developer Preview is not a production release. Review
[security](../../architecture/SECURITY_CONTRACT.md),
[known limitations](../../acceptance/KNOWN_LIMITATIONS.md) and the
[release checklist](../../acceptance/PUBLIC_RELEASE_CHECKLIST.md).

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

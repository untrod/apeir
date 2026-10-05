# Security Policy

## Supported versions

| Version | Status |
| --- | --- |
| `0.1.0-rc1` | Release candidate; security fixes accepted |
| Earlier versions | Unsupported; no public Distribution release |

## Reporting a vulnerability

Report suspected vulnerabilities privately through
[GitHub Security Advisories](https://github.com/untrod/apeir/security/advisories/new).
Do not open a public issue containing credentials, private data, exploit
details, or instructions for bypassing approvals.

Include the affected version, component, reproduction conditions, impact, and
any proposed mitigation. Redact provider keys, prompts, conversation content,
workspace paths, device identities, and Runtime state.

## Security model

APEIR treats identity, authorization, approval, delegation, credentials, and
audit records as Runtime boundaries. Agents and plans use SecretHandle identifiers; credentials resolve only at the
authorized execution boundary with scoped, expiring leases and centralized
redaction. Legacy provider configuration may reference environment/secret stores,
but raw values must never enter ordinary Work, evidence, events or audit. The Server Runtime remains
authoritative; Desktop, IDE, mobile, terminal, and device clients are control
surfaces.

APEIR is not a complete operating-system sandbox. Operators remain responsible
for process isolation, network controls, provider policies, and data governance.
Review the [threat model](docs/architecture/security/THREAT_MODEL.md),
[trust boundaries](docs/architecture/security/TRUST_BOUNDARIES.md), and
[known limitations](docs/acceptance/KNOWN_LIMITATIONS.md) before deployment.

Component-lock contracts passing do not establish native binary integrity.
Actual SHA-256 verification is required for verified releases. Physical and
provider qualification limits are recorded in [ROADMAP](ROADMAP.md).

## Disclosure

The maintainers will acknowledge actionable reports, investigate impact, and
coordinate remediation and disclosure according to severity and maintainer
availability. Do not publish a vulnerability before a coordinated disclosure
or explicit maintainer approval.

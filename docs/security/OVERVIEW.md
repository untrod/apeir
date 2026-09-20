# Security Overview

Nous treats identity, permissions, approvals, credentials, audit records, and
execution evidence as Runtime boundaries.

## Principles

- Fail closed when authorization or approval evidence is missing.
- Keep the Server Runtime authoritative.
- Store credential references instead of secret values.
- Redact secrets from logs, events, traces, configuration exports, and reports.
- Keep optional clients and providers outside the trusted kernel boundary.
- Require explicit review for remote access and destructive actions.

## Review documents

- [Threat model](THREAT_MODEL.md)
- [Trust boundaries](TRUST_BOUNDARIES.md)
- [Abuse cases](ABUSE_CASES.md)
- [Pack trust model](PACK_TRUST_MODEL.md)
- [Supply-chain security](SUPPLY_CHAIN_SECURITY.md)
- [Security checklist](SECURITY_CHECKLIST.md)

Nous is not an operating-system sandbox. Process isolation, network policy,
provider terms, and organizational data governance remain deployment
responsibilities. Vulnerabilities must be reported through the process in
[`SECURITY.md`](../../SECURITY.md).
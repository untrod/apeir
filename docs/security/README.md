# Security Documentation

Nous treats identity, credentials, permissions, approvals, and audit records as
Runtime boundaries. Actions crossing a governance boundary must fail closed.

## Review entry points

- [Security overview](OVERVIEW.md)
- [Threat model](THREAT_MODEL.md)
- [Trust boundaries](TRUST_BOUNDARIES.md)
- [Abuse cases](ABUSE_CASES.md)
- [Pack trust model](PACK_TRUST_MODEL.md)
- [Supply-chain security](SUPPLY_CHAIN_SECURITY.md)
- [Security checklist](SECURITY_CHECKLIST.md)

Report vulnerabilities privately using [`SECURITY.md`](../../SECURITY.md).
Do not publish credentials, private Runtime state, exploit instructions, or
approval-bypass details in a public issue.
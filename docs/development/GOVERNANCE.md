# Governance v1.0

## Roles

| Role | Responsibility |
|------|----------------|
| **Maintainer** | Merge PRs, cut releases, enforce architecture |
| **Contributor** | Submit PRs, review others, report issues |
| **Pack Author** | Create and maintain packs |
| **User** | Install, use, report issues |

## Decision Making

- **Kernel changes**: Require maintainer approval + architecture review
- **Provider additions**: Any contributor can submit
- **Pack additions**: Any pack author can publish
- **Documentation**: Any contributor can improve

## Architecture Review

Changes to these areas require architecture review:
- `nous_core/` modules
- Provider ABC interface
- Capability contract
- Pack manifest schema
- Public API endpoints

## Release Authority

- Maintainer approves and tags releases
- Release follows RELEASE_PROCESS.md
- Breaking changes require MAJOR version bump

## Code of Conduct

See CODE_OF_CONDUCT.md. One strike policy for malicious contributions.

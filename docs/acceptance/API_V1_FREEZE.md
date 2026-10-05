# API v1 Compatibility Policy

## Scope

The `/api/v1/` HTTP surface, public CLI commands, and documented SDK entry
points are compatibility surfaces for the 2.0 release line.

## Rules

- Additive fields and endpoints may be introduced in a backward-compatible
  minor release.
- Existing fields must not change type or meaning within the release line.
- Required request fields must not be added to an existing operation.
- Error responses must use the Nous error model rather than provider-specific
  structures.
- Authentication, authorization, approval, and audit checks must be identical
  for canonical and compatibility routes.
- Deprecated paths must emit a warning or metric and document the replacement.
- Removal requires a major release or an explicitly documented security action.

## Legacy aliases

Pre-versioned `/api/...` aliases may remain while callers migrate. They must
resolve to the same handlers and governance policy as `/api/v1/...`; they must
not become an independent implementation.

## Change review

Every compatibility change must include tests, migration impact, security
impact, and changelog documentation. The authoritative route table and tests are
more current than examples copied into design reports.
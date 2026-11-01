# Project governance

<!-- Compatibility anchors for existing documentation links. -->
<a name="governance-v10"></a>


This page concerns project decisions. Runtime authorization is defined by the
[security contract](../architecture/SECURITY_CONTRACT.md), not repository roles.

## Roles

Maintainers review integration/release decisions. Contributors propose changes,
review code and report problems. Pack/Provider authors follow the same contribution
process; publishing source does not make it trusted or authorized in a Runtime.

## Decision Making

[CONTRIBUTING](../../CONTRIBUTING.md) owns branch, review, test and merge rules.
`main` is the only permanent development branch. Kernel is frozen unless its
separate change is explicitly authorized; a documentation PR does not grant that
authorization. SDK/schema compatibility changes require their existing review.

## Architecture Review

Read the canonical contracts before changing admission, authority, execution,
evidence, state ownership or public interfaces. Reuse existing owners; do not
create a second Registry or permission authority to integrate an extension.

## Release Authority

Follow the [Release Runbook](../acceptance/RELEASE_RUNBOOK.md) and
[version policy](VERSIONING_POLICY.md). Signing/publication require explicit
maintainer approval. A milestone tag or internal unsigned artifact is not a
stable Release or an installed-platform qualification.

## Code of Conduct

The root [Code of Conduct](../../CODE_OF_CONDUCT.md) is the community policy.
[SECURITY](../../SECURITY.md) describes private vulnerability reporting.
This page adds no separate enforcement rule or support SLA.

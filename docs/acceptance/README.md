# Acceptance and release discipline

Current milestone status is maintained in [ROADMAP](../../ROADMAP.md).
These records have distinct scopes and are not blanket release certification.

- [Reality/Governance/simulation and M5 host-contract evidence](REALITY_ARCHITECTURE_AUDIT.md)
- [Engineering review, reproduced admission defects and research comparison](ENGINEERING_REVIEW.md)
- [Repository consolidation audit and document inventory](REPOSITORY_CONSOLIDATION.md)
- [Historical ARM64 host qualification](WINDOWS_ARM64_NATIVE_QUALIFICATION.md)
- [R6 baseline](R6_BASELINE.md) and [laptop evidence](R6_LAPTOP_CHECKPOINT.md)
- [Known limitations](KNOWN_LIMITATIONS.md)
- [Public release checklist](PUBLIC_RELEASE_CHECKLIST.md)
- [Release runbook](RELEASE_RUNBOOK.md) and [validation matrix](VALIDATION_MATRIX.md)
- [0.1.0-rc1 notes](RELEASE_NOTES_0.1.0-rc1.md) and [API compatibility](API_V1_FREEZE.md)

M3.3-C and M5 physical acceptance remain PENDING. Native component hash
validation is BLOCKED without the locked binaries. Generated evidence belongs
in retained CI/release artifacts, never private local data committed to source.

## Finding historical checkpoints

Published [`milestone/*` tags](https://github.com/untrod/apeir/tags) preserve
acceptance commits; they are not production versions or moving status pointers.
Use ROADMAP for current qualification, rather than inferring it from a tag name.
The 2026-10-16 ref audit retained all 31 existing checkpoints without moving,
renaming or deleting any tag; there were no published GitHub Releases.

| Tag family | Evidence scope |
| --- | --- |
| `milestone/m3.*` | Coordination, recovery, simulated Reality, Governance, Control Plane and SDK software |
| `milestone/m4*` | Provider references and bounded diagnostics; not complete interoperability |
| `milestone/m5*` | Host contracts; not physical write or power-loss acceptance |
| `milestone/developer-preview-*` | Documentation, source demos, SDK/CI and gallery; not native installation |
| Consolidation, ARM64 Lab and other named checkpoints | The distinct dated acceptance record and its exact commit |

For example, `git tag --list 'milestone/m3.*' --sort=version:refname` finds
Runtime/software checkpoints without browsing every ref. Two checkpoint names
may intentionally reference one commit when that state closes distinct scopes;
this does not make either acceptance record redundant. New development uses
short-lived PR branches, not additional permanent branches or speculative tags.

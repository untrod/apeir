# APEIR 0.1 source baseline

APEIR 0.1 is the maintained source baseline for governed, verifiable execution.
It is not a claim that every optional provider, device, or packaging target is
available on every host.

## Identity

- Public repository: `https://github.com/untrod/apeir`
- Public root commit: `4bafb6398da845dc3cfccb31e9eaa3be6feb8601`
- Version: `0.1.0-rc1`
- Kernel: an independently versioned, locked APEIR Kernel distribution
- Compatibility identifiers: existing `nous.*.v1`, `NOUS_*`, and `nous-*`
  protocol, environment, and executable names remain valid where documented.

The public root commit is the clean source import. Later commits on the 0.1
line may correct release automation, portability, security, or correctness
without changing the architectural authority boundary.

## Frozen authority boundary

The following behavior is part of the 0.1 architecture freeze:

- effectful operations require Kernel admission;
- Permit and Lease authority is owned by the Kernel;
- Runtime and Desktop clients do not write the Kernel journal directly;
- NKI incompatibility and an unavailable production Kernel fail closed;
- task, artifact, event, receipt, and deployment state remain durable;
- artifact identity is content-addressed and verified before use;
- extension and network operations retain explicit policy and bounded scope;
- success claims require recorded execution results or independent evidence;
- LLM-OFF execution remains a supported operating mode.

Changes to these invariants require a security or correctness justification,
an explicit compatibility analysis, and independent verification. New product
features are not sufficient justification.

## Allowed maintenance

The 0.1 line accepts security fixes, correctness fixes, compatibility fixes,
release blockers, documentation corrections, and test improvements. Research
work must use stable contracts and must not introduce a parallel Permit,
Lease, policy, journal, task lifecycle, or receipt implementation.

## Release status

The source baseline and the binary release have separate gates. Source may be
published after clean-clone CI and repository hygiene pass. Binary publication
remains blocked until all target-native packages have maintainer signing,
provenance, hashes, SBOM validation, and an enabled Windows Defender scan on a
clean Windows 10 x64 host. A blocked binary gate must not be presented as
passed.

## Research boundary

Autonomous engineering experiments live under `research/engineering-loop/`.
They integrate professional tools through adapters and use the existing APEIR
contracts. Experimental results do not become 0.1 guarantees.

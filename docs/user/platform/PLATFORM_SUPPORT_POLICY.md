# Platform Support Policy

Nous distinguishes declared compatibility, continuous-integration targets, and
locally validated release evidence.

## Support levels

- Validated: all release gates passed on recorded hardware and software.
- CI target: automated jobs are defined; the release requires a passing remote
  run against the reviewed commit.
- Limited: only a documented subset of Runtime capabilities is expected.
- Experimental: no compatibility commitment.

## RC2 status

| Platform | Level | Notes |
| --- | --- | --- |
| Windows 10 ARM64, Python 3.12 | Validated locally | Runtime, CLI, Wheel, and Desktop web build |
| Windows x64 | CI target | Native packaging requires remote evidence |
| Linux x64 and ARM64 | CI target | Runtime and package jobs are defined |
| macOS | CI target | Runtime and Desktop jobs require remote evidence |
| ARMv7 Lite | Limited | No heavy local model, vector, or GUI dependencies |

A release report must identify the exact operating system, architecture, Python
version, optional dependencies, and commands executed. Package metadata alone
is not validation evidence.
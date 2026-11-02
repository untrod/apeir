# Platform Support Policy

APEIR distinguishes declared compatibility, software CI, native build and
installed lifecycle. Each result applies only to its recorded revision and
actual OS/architecture. [ROADMAP](../../../ROADMAP.md) owns current status.

## Support levels

- Software CI: the relevant automated checks passed for the stated source.
- Native build: real target binaries passed their component/build checks.
- Installed qualification: the actual target OS completed its lifecycle checks.
- Limited/experimental: only the recorded subset is supported or proposed.

## Current Preview scope

| Target | Recorded scope | Does not establish |
| --- | --- | --- |
| Linux amd64 / ARM64 | Runtime/CLI and architecture CI | Every distribution, strict environment execution or physical Jetson work |
| macOS 15 ARM64 | Runtime software CI | A qualified native Desktop installer |
| Windows x64 hosted runner | Runtime CI; approved real Server2025 native build and sidecar Smoke | Windows 10 GUI, install/upgrade/uninstall or Defender acceptance |
| Windows ARM64 | Current metadata check; separate historical host record | Current native application or installation acceptance |
| ARMv7 Lite | Limited nonblocking CI profile | Full local-model, scientific or Desktop support |

Use the [Windows x64 build record](../deployment/WINDOWS_10_X64_LAUNCHER.md#current-native-command-qualified-build),
[historical ARM64 host record](../deployment/WINDOWS_10_ARM64_LOCAL.md) and
[Quick Start](../getting-started/QUICK_START.md) for the exact available path.

## Historical policy

The RC2 table below is retained as its original qualification snapshot, not the
status of the current Preview. It must not promote metadata CI or an old source
build into a current native-install PASS.

<details>
<summary>Archived RC2 table</summary>

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

</details>

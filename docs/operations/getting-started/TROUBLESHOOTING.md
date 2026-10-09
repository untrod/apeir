# Troubleshooting

Use the [source Quick Start](QUICK_START.md) first. Keep the exact failing
command, interpreter version, operating system and traceback.

## Installation or command discovery

Check `python --version` (supported source development: 3.10–3.12), activate
the checkout's virtual environment, then run `python -m pip check` and
`apeir --help`. From the checkout, `python -m pip install -e .` installs the
current package; obsolete package names and guessed images are unsupported.

Do not run as Administrator or delete an entire configuration directory to
work around a permission error. Inspect the specific workspace and use a
fresh writable directory when reproducing an installation problem.

## Runtime, Providers and recovery

`apeir doctor` and `apeir status` inspect the environment. Missing Kernel,
credential, device or strong isolation backend must be reported; do not
enable a test-only isolation override.
Use the [Provider guide](../guides/PROVIDER_GUIDE.md) for endpoint diagnostics.
Redact credentials and private data before sharing.

For an uncertain mutation, preserve Work/Operation IDs and evidence and use
the existing recovery path. Do not retry an effect because a response was lost;
a Receipt or model statement cannot replace a fresh Observation.

Process-lifecycle tests require the
[supported environment](../../development/DEVELOPER_PLATFORM.md#supported-development-environment),
including a reaper in containers. Known qualification limits live in
[ROADMAP](../../../ROADMAP.md).

Report bugs at [GitHub](https://github.com/untrod/apeir/issues).
Security concerns follow [SECURITY](../../../SECURITY.md).

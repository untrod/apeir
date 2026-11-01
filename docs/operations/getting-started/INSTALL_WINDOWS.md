# Windows source installation

For the unsigned x64 test package, use [Windows Development Build](QUICK_START.md#native-installation).
It is separate from the source path below; Windows10 installed lifecycle remains
pending and no stable installer is offered.

Follow the [source Quick Start](QUICK_START.md), including PowerShell virtual
environment activation. Use Python 3.10–3.12 and a writable checkout;
Administrator privileges are unnecessary for a source install.

If `apeir` is not found, activate the same environment used by `python -m pip`.
Native Tauri packaging requires Rust, MSVC/Windows SDK and locked native
components. Windows ARM64 has a separate
[qualification guide](../deployment/WINDOWS_10_ARM64_LOCAL.md); source installation
does not qualify native binaries or isolation backends.

See [installation notes](../INSTALLATION.md) and [troubleshooting](TROUBLESHOOTING.md).

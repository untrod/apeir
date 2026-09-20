# Windows 10 ARM64 Local Deployment

This guide documents the Xiaomi Snapdragon device used for Nous 2.0.0-rc3 validation.

## Supported workflow on this device

| Item | Current status |
| --- | --- |
| Windows | Windows 10 ARM64, build 19045 |
| Python | 3.12.10 ARM64 |
| Node.js | 24.16.0 ARM64 |
| Rust | 1.97.1 ARM64 MSVC target installed |
| WebView2 | Installed |
| Frontend validation | Supported locally |
| Runtime and CLI | Supported locally |
| Native Tauri linking | Not supported on this operating system |

Microsoft supports the native ARM64 Visual Studio 2022 C++ toolchain on Windows 11 on Arm, not Windows 10 ARM64. The Runtime and frontend can be developed and tested on this device, but the signed/native Tauri installer must be produced by the repository's `windows-11-arm` GitHub Actions job or another supported Windows 11 ARM64 build machine.

## Run Nous from the checkout

```powershell
Set-Location <repository>
.\.venv\Scripts\Activate.ps1
python --version
where.exe nous
nous doctor
nous status
nous models doctor
nous demo
```

Refresh the editable installation after pulling changes:

```powershell
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

## Configure a Provider safely

```powershell
nous provider add
nous provider status
nous provider doctor deepseek
```

When the wizard asks for an environment variable name, enter a name such as `DEEPSEEK_API_KEY`, not the secret value. Set the value outside Nous and open a new terminal:

```powershell
[Environment]::SetEnvironmentVariable(
  "DEEPSEEK_API_KEY",
  "replace-with-a-new-key",
  "User"
)
```

Revoke any key that has appeared in a screenshot, terminal transcript, issue, or chat. Nous stores only credential references.

## Run the Runtime API

```powershell
nous runtime-api start
```

In a second terminal:

```powershell
nous runtime-api status
```

The Runtime binds to loopback by default, creates an ephemeral desktop session token, and removes it on normal shutdown. Repeated starts bind before rotating the token, so a port conflict cannot invalidate an existing session.

## Validate the desktop frontend locally

```powershell
Set-Location <repository>\desktop
npm ci
npm run lint
npm test
npm run build
```

This validates the React Hook rules, startup state machine, UI-state migration, TypeScript, and production Vite bundle. `npm run dev` opens a development web surface; it is not the installed desktop product.

## Obtain the native ARM64 desktop application

1. Push the RC3 branch to GitHub.
2. Open the `Desktop Build` workflow.
3. Wait for the `Build Windows ARM64` job on `windows-11-arm`.
4. Download the `windows-arm64-nsis` artifact.
5. Verify its SHA-256 value against `SHA256SUMS-arm64.txt`.
6. Run the NSIS installer and launch Nous from the Start menu.

The installer contains the React production bundle, the Tauri native shell, and the packaged Nous Runtime sidecar. It is an application backed by WebView2, not a separately hosted website. The desktop shell starts or reconnects to the local Runtime and stores Runtime logs under `%LOCALAPPDATA%\Nous\logs`.

## Development-only desktop configuration

When running an unpackaged checkout, configure path references once:

```powershell
[Environment]::SetEnvironmentVariable(
  "NOUS_CLI_PATH",
  "<repository>\.venv\Scripts\nous.exe",
  "User"
)
[Environment]::SetEnvironmentVariable(
  "NOUS_WORKSPACE_ROOT",
  "<repository>",
  "User"
)
```

Do not set `NOUS_API_TOKEN` permanently. Do not expose the Runtime listener to the LAN without explicit authentication and transport security.

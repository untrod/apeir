# Install APEIR on Windows

[**Download x64**](https://github.com/untrod/apeir/actions/runs/45505843403/artifacts/14976528487) ·
[**Download ARM64**](https://github.com/untrod/apeir/actions/runs/45505847685/artifacts/14977666664) ·
[Version and checksums](QUICK_START.md#download-metadata)

Each bundle contains Setup and Portable. You do not need to install Python,
Node.js or Rust to use either one.

下载对应架构的包并解压，安装版和 Portable 选一种即可。模型可以稍后配置。

## Requirements

- **Architecture:** x64 for Intel/AMD Windows; ARM64 for Windows on Arm.
- **WebView2:** Setup can download Microsoft's WebView2 runtime when it is missing.
  Portable also needs WebView2 installed.
- **Storage:** a writable application directory and a project folder.

<a name="known-limitations"></a>

Version **0.1.0-rc1** is an unsigned Developer Preview. GitHub sign-in is required
for these Actions downloads. See [expiry dates by architecture](QUICK_START.md#download-metadata).
Windows 10 install, upgrade and uninstall testing is pending on physical hardware.
If Windows blocks the application, keep the exact message for troubleshooting;
do not disable Defender or SmartScreen.

## Verify the download

Extract the outer GitHub ZIP. In PowerShell, check the installer or Portable ZIP:

```powershell
Get-FileHash -Algorithm SHA256 .\APEIR_0.1.0-rc1_x64-setup.exe
```

Use the matching filename for ARM64. Compare the result with
[Download metadata](QUICK_START.md#download-metadata). Stop if it differs.
`SHA256SUMS.txt` and the source manifest are also included in the bundle.

## Setup

1. Open `APEIR_0.1.0-rc1_x64-setup.exe` or `APEIR_0.1.0-rc1_arm64-setup.exe`.
2. Follow Setup. It installs for the current user; no manual elevation is needed.
3. Open APEIR, choose a project folder and enter Studio.
4. Open **Files** or **Workflow**. To connect a model, use
   **Settings → Models & credentials** and follow the [model guide](../guides/PROVIDER_GUIDE.md).

## Portable

1. Extract the included `APEIR-Portable-0.1.0-rc1-windows-x64.zip` or ARM64 ZIP.
2. Open `APEIR-Portable/APEIR.exe`.
3. Keep all files in that folder together, including the service executables and DLLs.

Portable keeps application state under `%LOCALAPPDATA%\Nous`, just like Setup.
Your selected project folder holds project state. The `Nous` directory name is
retained for compatibility; Portable does not keep all data beside the EXE.

<a name="download-with-github-cli"></a>

## Download with GitHub CLI

With [GitHub CLI](https://cli.github.com/) installed and authenticated, run this
in PowerShell. Set `$apeirArch` to `arm64` for Windows on Arm:

```powershell
$apeirArch = 'x64' # or 'arm64'
$apeirPackages = @{
    x64 = @{ Run = '45505843403'; Setup = '7cb7697c13df348d15f253cb4aa68e96082ac40817229363321d63a6ee54fcfa'; Portable = 'cb3f43d2f4181bb76820c3d47df874ded262945ca73cc176c627d7869f2a80b0' }
    arm64 = @{ Run = '45505847685'; Setup = 'b7194ae5c0d710942cdd668bf86648a01e1d04ca97d8d617a1f8762434bd4f54'; Portable = 'ed1aab1a3093ebc7a6038bfaa07b2a7f0f4615b3566f038103b122ff1e632dc2' }
}
if (!$apeirPackages.ContainsKey($apeirArch)) { throw 'Choose x64 or arm64' }
$apeirPackage = $apeirPackages[$apeirArch]
$apeirDestination = ".\apeir-rc1-$apeirArch"
if (Test-Path -LiteralPath $apeirDestination) { throw 'Choose a new download directory' }
gh run download $apeirPackage.Run --repo untrod/apeir --name "windows-$apeirArch-native-development-build" --dir $apeirDestination
if ($LASTEXITCODE -ne 0) { throw 'Download failed' }
$apeirFiles = @{
    "APEIR_0.1.0-rc1_$apeirArch-setup.exe" = $apeirPackage.Setup
    "APEIR-Portable-0.1.0-rc1-windows-$apeirArch.zip" = $apeirPackage.Portable
}
foreach ($apeirName in $apeirFiles.Keys) {
    $apeirPath = Join-Path $apeirDestination $apeirName
    $apeirHash = (Get-FileHash -LiteralPath $apeirPath -Algorithm SHA256 -ErrorAction Stop).Hash
    if ($apeirHash -ne $apeirFiles[$apeirName]) { throw "SHA-256 mismatch: $apeirName" }
}
Write-Host 'Verified. Open Setup or extract Portable when ready.'
```

This downloads and verifies both files. It does not start an installer or
request administrator access.

## Updates and your data

Back up the project folder and `%LOCALAPPDATA%\Nous` before testing an upgrade.
Use a copy when checking older workspaces. Uninstalling the application should
not be treated as a way to erase project data; keep your backup independently.

## Exit, recovery and troubleshooting

Close APEIR normally. On reopening, return to the saved project and task history.
If a request lost its response, inspect the original task before submitting it
again. Closing a panel does not cancel a running task.

Startup logs are under `%LOCALAPPDATA%\Nous\logs`, normally `runtime-api.log`
and `nousd.log`. Include the app version, Windows version and exact error when
reporting a problem. Remove keys, tokens and personal paths from log excerpts;
do not upload the whole state directory.

For source installation, use [Quick Start](QUICK_START.md).
For build and platform details, see the [launcher reference](../deployment/WINDOWS_10_X64_LAUNCHER.md)
and [Windows ARM64 notes](../deployment/WINDOWS_10_ARM64_LOCAL.md).

# APEIR on Windows

The current **0.1.0-rc1 development bundle** contains both an installer and a
Portable ZIP. Pick one; you do not need to install Python or Kernel separately.

[**Download Setup + Portable**](https://github.com/untrod/apeir/actions/runs/41467950136/artifacts/13157732606)
· [Version, hashes and source](QUICK_START.md#download-metadata)

This is an **unsigned development build**, not a stable Release. GitHub sign-in
is required; the artifact expires on **2026-11-16**. Build and real sidecar checks
passed on Windows Server 2025. Windows 10 installation, GUI, upgrade, uninstall
and Defender acceptance are **PENDING**. There is no public Release asset yet.

中文速读：下载上面的工件，解压后任选安装版或 Portable。先校验，再打开；
暂时没有 Windows 10 实机验收，不要把工作资料当测试沙盒。模型可以稍后配置。

## Known limitations

This bundle includes the Windows concurrent Artifact-lock correction. Its full
build and native component checks passed; the installer has not been exercised
on Windows10. GUI startup, upgrade, uninstall, Defender and old-workspace
compatibility remain **PENDING**.

A separate intermittent Windows Context persistence timeout remains under
[investigation](https://github.com/untrod/apeir/issues/116). Exact-source CI passed
on retry; that does not establish its root cause. After an uncertain response,
query the original Work/Run rather than submitting the operation again.

## Before opening a package

- Use **x64 Windows**. Windows 10 x64 is the intended target; this candidate has
  not completed acceptance on it. Windows ARM64 is a separate qualification.
- The desktop needs **Microsoft Edge WebView2**. Setup uses its download
  bootstrapper when necessary, so first installation can require network access.
- Keep the included sidecars and app-local runtime DLLs together. Their presence
  was checked in the build; clean Windows 10 dependency acceptance is still pending.
- Start with a **new, empty workspace**. Back up existing workspace and application
  state before testing an upgrade. Use an isolated copy for migration tests.

Extract the outer GitHub artifact ZIP. Compare the Setup or Portable file's
SHA-256 with [Download metadata](QUICK_START.md#download-metadata), not with the
outer ZIP hash. In PowerShell, `Get-FileHash -Algorithm SHA256 <file>` prints it.
A mismatch means **stop**. Do not run a similarly named file from another source.

The bundle also contains `SHA256SUMS.txt`, manifests and native validation
reports. Its binary source is `67186696426cad60b55fc3576dfde8b93defbb37`;
a newer README or screenshot does not change that binary.

## Setup

1. After verification, open `APEIR_0.1.0-rc1_x64-setup.exe`.
2. Setup is configured for the **current user**. Do not add administrator
   elevation to work around a failure. Allow the supported WebView2 prerequisite
   installation if it is needed and acceptable on your machine.
3. Open APEIR and select a new workspace. Check the displayed Runtime and Kernel
   status. A missing model is **UNCONFIGURED**, not a reason to lose read-only access.
4. Open **Files**, **Workflow** or the supported model-free Demo. Add Provider
   credentials later through the supported secure configuration flow.

An unsigned application can receive Windows security warnings. If Windows blocks
it, stop and retain the exact warning for review. Do not disable Defender,
SmartScreen or other protection to make the test pass.

## Portable

1. Verify `APEIR-Portable-0.1.0-rc1-windows-x64.zip`.
2. Extract the **whole ZIP** into a writable directory.
3. Open `APEIR-Portable/APEIR.exe` from the extracted package. Do not move only
   the EXE: Kernel, Worker and Runtime sidecars are part of the application.
4. Follow the same workspace and service checks as Setup.

“Portable” describes the application package. It does **not** mean all user data
stays beside the EXE. The launcher uses `%LOCALAPPDATA%\Nous` for application
configuration, logs and local service state, plus your selected workspace for
project state. `Nous` is a retained compatibility directory name.

## Download with GitHub CLI

For developers who already use authenticated `gh`, this is the exact current
artifact. It downloads files; it does **not** start installation:

```powershell
gh run download 41467950136 --repo untrod/apeir --name windows-x64-native-development-build --dir .\apeir-0.1.0-rc1
if ($LASTEXITCODE -ne 0) { throw 'Download failed; no installer was run.' }
$apeirFiles = @{
    'APEIR_0.1.0-rc1_x64-setup.exe' = '0c2a65bcfe1ac31108d7a99b03511bdc1ee9e22230fed55918e03c427bd21e18'
    'APEIR-Portable-0.1.0-rc1-windows-x64.zip' = '077fc0ff0bad9621ba7a777a887a1155f13244e3bcb3a512a403eddba0452aa1'
}
foreach ($apeirName in $apeirFiles.Keys) {
    $apeirPath = Join-Path '.\apeir-0.1.0-rc1' $apeirName
    if (!(Test-Path -LiteralPath $apeirPath)) { throw "Missing package: $apeirName" }
    $apeirHash = (Get-FileHash -LiteralPath $apeirPath -Algorithm SHA256).Hash
    if ($apeirHash -ne $apeirFiles[$apeirName]) { throw "SHA-256 mismatch: $apeirName" }
}
Write-Host 'Package hashes match. No installer was run.'
```

Use a new destination directory. These fixed hashes refer only to the files
above. The actual archive and hash guards were independently checked with PowerShell
on Linux, including mismatch, missing-file and download-failure refusal.
Target-machine download and installation still need execution. Public, no-login
Release downloads will be documented only after their actual publication.

## Exit, recovery and troubleshooting

Close the application normally, reopen it and inspect the original project and
Work records. A lost response is a reason to query the original operation, not
to submit its effects again. Closing a panel does not cancel background Work.

Launcher logs normally live under `%LOCALAPPDATA%\Nous\logs`:
`runtime-api.log` and `nousd.log`. If startup fails, record the application
version, Windows version, warning text and relevant log excerpt. Remove tokens,
credentials and personal paths before sharing diagnostics. Do not upload the
whole state directory.

Upgrade, uninstall, reinstall, retained-data behavior and child-process cleanup
still need Windows 10 acceptance. Back up state first; do not assume uninstall
removes your workspace, or manually delete it as a troubleshooting shortcut.
The [launcher reference](../deployment/WINDOWS_10_X64_LAUNCHER.md) and
[Release Runbook](../../acceptance/RELEASE_RUNBOOK.md) retain the engineering
checks and the pending installation lifecycle.

## Windows source installation

Follow [Source Preview](QUICK_START.md#source-preview) or
[Developer Setup](QUICK_START.md#developer-setup). Activate the same virtual
environment used by `python -m pip`; no administrator privilege is needed.
Native development additionally requires Rust, MSVC/Windows SDK and locked
components. [Windows ARM64](../deployment/WINDOWS_10_ARM64_LOCAL.md) has a separate
support scope. See [troubleshooting](TROUBLESHOOTING.md) for source startup issues.

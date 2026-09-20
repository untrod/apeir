param(
    [string]$Workspace = "$env:USERPROFILE\NousValidation\p1-p5-project-final",
    [string]$ProviderConfig = "$env:USERPROFILE\NousWorkspace\.nous\providers.json",
    [int]$KernelPort = 18772,
    [switch]$ProviderToolProbe,
    [switch]$ProviderWorkerTransportProbe
)

$ErrorActionPreference = "Stop"

Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class NousAcceptanceCredential {
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
    public struct CREDENTIAL {
        public uint Flags;
        public uint Type;
        public IntPtr TargetName;
        public IntPtr Comment;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
        public uint CredentialBlobSize;
        public IntPtr CredentialBlob;
        public uint Persist;
        public uint AttributeCount;
        public IntPtr Attributes;
        public IntPtr TargetAlias;
        public IntPtr UserName;
    }

    [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern bool CredRead(string target, uint type, uint flags, out IntPtr credential);

    [DllImport("advapi32.dll")]
    public static extern void CredFree(IntPtr buffer);
}
'@

$credentialPointer = [IntPtr]::Zero
$credentialBytes = $null
$credentialText = $null
$kernelProcess = $null
$previousPythonPath = $env:PYTHONPATH
$previousPath = $env:PATH

try {
    $found = [NousAcceptanceCredential]::CredRead(
        "Nous/provider-env/DEEPSEEK_API_KEY",
        1,
        0,
        [ref]$credentialPointer
    )
    if (-not $found) {
        throw "Configured DeepSeek credential was not found."
    }

    $record = [Runtime.InteropServices.Marshal]::PtrToStructure(
        $credentialPointer,
        [type][NousAcceptanceCredential+CREDENTIAL]
    )
    $credentialBytes = New-Object byte[] $record.CredentialBlobSize
    [Runtime.InteropServices.Marshal]::Copy(
        $record.CredentialBlob,
        $credentialBytes,
        0,
        $credentialBytes.Length
    )
    $utf8 = New-Object Text.UTF8Encoding($false, $true)
    $credentialText = $utf8.GetString($credentialBytes)

    $env:DEEPSEEK_API_KEY = $credentialText
    $env:NOUS_ALLOWED_CREDENTIALS = "DEEPSEEK_API_KEY"
    $repoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
    $env:PYTHONPATH = $repoRoot
    $env:PATH = "$repoRoot\.venv\Scripts;$previousPath"
    $env:NOUS_NKI_TOKEN = (
        [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
    )

    $kernelRoot = Join-Path $env:TEMP (
        "nous-acceptance-kernel-" + [guid]::NewGuid().ToString("N")
    )
    New-Item -ItemType Directory -Path $kernelRoot | Out-Null
    $kernelOutput = Join-Path $kernelRoot "kernel.out.log"
    $kernelError = Join-Path $kernelRoot "kernel.err.log"
    $kernelProcess = Start-Process `
        -FilePath "$env:LOCALAPPDATA\Nous\nousd.exe" `
        -ArgumentList @(
            "serve",
            (Join-Path $kernelRoot "journal.db"),
            "$env:LOCALAPPDATA\Nous\nous-provider-worker.exe",
            "127.0.0.1:$KernelPort"
        ) `
        -RedirectStandardOutput $kernelOutput `
        -RedirectStandardError $kernelError `
        -WindowStyle Hidden `
        -PassThru

    $kernelReady = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        Start-Sleep -Milliseconds 250
        try {
            $client = [Net.Sockets.TcpClient]::new()
            $client.Connect("127.0.0.1", $KernelPort)
            $kernelReady = $client.Connected
            $client.Dispose()
            if ($kernelReady) {
                break
            }
        } catch {
            $kernelReady = $false
        }
    }
    if (-not $kernelReady) {
        throw "Acceptance kernel did not become ready."
    }

    if ($ProviderToolProbe) {
        & "$PSScriptRoot\..\..\.venv\Scripts\python.exe" `
            "$PSScriptRoot\provider_tool_call_probe.py"
    } elseif ($ProviderWorkerTransportProbe) {
        & "$PSScriptRoot\..\..\.venv\Scripts\python.exe" `
            "$PSScriptRoot\provider_worker_transport_probe.py" `
            --kernel-endpoint "tcp://127.0.0.1:$KernelPort"
    } else {
        & "$PSScriptRoot\..\..\.venv\Scripts\python.exe" `
            "$PSScriptRoot\project_collaboration_acceptance.py" `
            --workspace $Workspace `
            --provider-config $ProviderConfig `
            --kernel-endpoint "tcp://127.0.0.1:$KernelPort"
    }
    if ($LASTEXITCODE -ne 0) {
        throw "P1-P5 real acceptance failed with exit code $LASTEXITCODE."
    }
} finally {
    if ($kernelProcess -and -not $kernelProcess.HasExited) {
        Stop-Process -Id $kernelProcess.Id
    }
    $env:DEEPSEEK_API_KEY = $null
    $env:NOUS_NKI_TOKEN = $null
    $env:NOUS_ALLOWED_CREDENTIALS = $null
    $env:PYTHONPATH = $previousPythonPath
    $env:PATH = $previousPath
    if ($credentialBytes) {
        [Array]::Clear($credentialBytes, 0, $credentialBytes.Length)
    }
    $credentialText = $null
    if ($credentialPointer -ne [IntPtr]::Zero) {
        [NousAcceptanceCredential]::CredFree($credentialPointer)
    }
}

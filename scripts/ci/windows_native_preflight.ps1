param(
    [string]$Target = "aarch64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"
$targetArchitecture = if ($Target -match "^aarch64-") { "arm64" } elseif ($Target -match "^x86_64-") { "x64" } else { "" }
if (-not $targetArchitecture) {
    throw "Unsupported Windows MSVC target: $Target"
}

$osArchitecture = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
$processArchitecture = [Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture.ToString()
$canExecuteTarget = if ($targetArchitecture -eq "arm64") {
    $osArchitecture -eq "Arm64"
} else {
    $osArchitecture -in @("X64", "Arm64")
}

$cargo = Get-Command cargo -ErrorAction SilentlyContinue
$rustc = Get-Command rustc -ErrorAction SilentlyContinue
$vswhere = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
$installation = $null
$toolset = $null
$clPath = $null
$linkPath = $null
if (Test-Path -LiteralPath $vswhere) {
    $installation = (& $vswhere -latest -products * -property installationPath | Select-Object -First 1)
    if ($installation) {
        $toolsRoot = Join-Path $installation "VC\Tools\MSVC"
        if (Test-Path -LiteralPath $toolsRoot) {
            $toolset = Get-ChildItem -LiteralPath $toolsRoot -Directory |
                Where-Object {
                    Test-Path -LiteralPath (Join-Path $_.FullName "bin\Host$targetArchitecture\$targetArchitecture\cl.exe")
                } |
                Sort-Object { [version]$_.Name } -Descending |
                Select-Object -First 1
            if ($toolset) {
                $clPath = Join-Path $toolset.FullName "bin\Host$targetArchitecture\$targetArchitecture\cl.exe"
                $linkPath = Join-Path $toolset.FullName "bin\Host$targetArchitecture\$targetArchitecture\link.exe"
            }
        }
    }
}

$sdkLib = $null
$sdkRoot = "C:\Program Files (x86)\Windows Kits\10\Lib"
if (Test-Path -LiteralPath $sdkRoot) {
    $sdkLib = Get-ChildItem -LiteralPath $sdkRoot -Directory |
        Sort-Object { try { [version]$_.Name } catch { [version]"0.0" } } -Descending |
        ForEach-Object { Join-Path $_.FullName "um\$targetArchitecture\kernel32.lib" } |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1
}

$missing = [Collections.Generic.List[string]]::new()
if (-not $canExecuteTarget) { $missing.Add("Windows host capable of executing $targetArchitecture binaries") }
if (-not $cargo) { $missing.Add("cargo") }
if (-not $rustc) { $missing.Add("rustc") }
if (-not $installation) { $missing.Add("Visual Studio 2022 C++ Build Tools") }
if (-not $clPath) { $missing.Add("MSVC $targetArchitecture cl.exe") }
if (-not $linkPath) { $missing.Add("MSVC $targetArchitecture link.exe") }
if (-not $sdkLib) { $missing.Add("Windows SDK kernel32.lib ($targetArchitecture)") }

[pscustomobject][ordered]@{
    ready = $missing.Count -eq 0
    target = $Target
    target_architecture = $targetArchitecture
    os_architecture = $osArchitecture
    process_architecture = $processArchitecture
    can_execute_target = $canExecuteTarget
    cargo_path = if ($cargo) { $cargo.Source } else { $null }
    rustc_path = if ($rustc) { $rustc.Source } else { $null }
    visual_studio_path = $installation
    cl_path = $clPath
    link_path = $linkPath
    kernel32_lib = $sdkLib
    missing = @($missing)
}

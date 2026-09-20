# Nous Runtime Deployment Guide

## Supported Platforms

| Platform | Architecture | Status |
|----------|-------------|--------|
| Windows 10/11 | x64 | Supported |
| Windows 10/11 | ARM64 | Supported (RC2) |
| Linux | x64, ARM64 | Supported |
| macOS | Apple Silicon, x64 | Planned |

## Windows ARM64 Desktop

### Prerequisites

- Windows 10 ARM64 or Windows 11 ARM64
- Visual Studio Build Tools 2022 with "Desktop development with C++"
- MSVC v143 ARM64 build tools
- Windows 10/11 SDK
- Node.js 20+
- Rust toolchain with `aarch64-pc-windows-msvc` target
- Python 3.10–3.12

### Build

```powershell
# Install Rust ARM64 target
rustup target add aarch64-pc-windows-msvc

# Install desktop dependencies
cd desktop
npm ci
npm run build

# Build ARM64 installer
npm run tauri:build:arm64
```

The NSIS installer is generated at `desktop/src-tauri/target/release/bundle/nsis/`.

### Verify

```powershell
nous doctor
nous models doctor
npm --prefix desktop run build
```

## Windows x64 Desktop

```powershell
cd desktop
npm ci
npm run build
npm run tauri:build
```

## Linux

### Python Runtime

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
nous doctor
```

### Desktop (experimental)

Requires webkit2gtk and Tauri system dependencies. See [Tauri prerequisites](https://v2.tauri.app/start/prerequisites/).

## Runtime Configuration

### Provider Credentials

Provider API keys are referenced by environment variable name, never stored in configuration files:

```bash
export OPENAI_API_KEY="sk-..."
export DEEPSEEK_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
```

Then configure:

```bash
nous provider add
```

### Model Configuration

```bash
nous models doctor
nous models list
nous models configure
```

## Workspace Structure

```
workspace/
├── nous.yaml          # Project configuration
├── models.yaml        # Model registry (optional)
├── data/              # Runtime data
├── packs/             # Installed packs
└── projects/          # Project artifacts
```

## Health Verification

```bash
# Full diagnostic
nous doctor

# Model subsystem
nous models doctor

# Runtime status
nous status

# Run demo (no API key required)
nous demo
```

## Production Deployment

For production deployments, review:

- [Security documentation](../../security/OVERVIEW.md)
- [Trust boundaries](../../security/TRUST_BOUNDARIES.md)
- [Known limitations](../../release/KNOWN_LIMITATIONS.md)
- [Release checklist](../../release/RELEASE_CHECKLIST.md)

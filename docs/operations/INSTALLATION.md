# Installation

## Requirements

- Python 3.10, 3.11, or 3.12
- Git
- A writable project directory
- Optional: Node.js for the Desktop web build
- Optional: Rust and Cargo for a native Tauri package

## Install from source

```powershell
git clone https://github.com/kicoyini45-blip/nous-runtime.git
cd nous-runtime
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
```

On Linux or macOS, activate the environment with:

```bash
source .venv/bin/activate
```

## Initialize and verify

```powershell
nous init --path .
nous doctor
nous status
nous models doctor
nous demo
```

The built-in demo does not require a cloud provider key.

## Development installation

```powershell
pip install -e ".[dev]"
ruff check nous_runtime tests
pytest
```

## Optional components

Install optional dependency groups only when required:

```powershell
pip install -e ".[desktop]"
pip install -e ".[ai-full]"
pip install -e ".[installer]"
```

Review platform availability before installing large model or vector packages.
Do not add provider credentials to `pyproject.toml`, YAML, source files, or Git.
# Install Nous on Windows

## Requirements
- Windows 10 or 11
- Python 3.10+ ([python.org](https://python.org))
- 4GB RAM (8GB+ recommended)

## Quick Install

```powershell
# 1. Install Python from python.org (check "Add to PATH")

# 2. Open PowerShell and install Nous
pip install nous-runtime[all]

# 3. Verify
nous version
nous doctor
```

## First Run

```powershell
nous init        # Interactive setup wizard
nous start       # Start the Runtime
nous             # Open interactive shell
```

## Service (Optional)

```powershell
# Register as Windows service
powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1 -RegisterService

# Start service
Start-Service nousd
```

## PATH

If `nous` is not found after install:
1. Open "Edit environment variables"
2. Add `%APPDATA%\Python\Python3XX\Scripts` to PATH
3. Restart terminal

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `nous` not found | Add Python Scripts to PATH |
| `chromadb` fails | `pip install chromadb --upgrade` |
| Permission denied | Run terminal as Administrator |
| Port 8770 in use | `netstat -ano | findstr 8770` |

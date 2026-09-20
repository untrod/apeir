# Troubleshooting Guide

## Installation

### `pip install` fails
```bash
pip install --upgrade pip
pip install nous-runtime[all] --no-cache-dir
```

### `nous` command not found
- Windows: Add `%APPDATA%\Python\Python3XX\Scripts` to PATH
- Linux/macOS: `export PATH="$HOME/.local/bin:$PATH"`
- Or: `python -m nous_runtime.cli.main`

### Python version too old
```bash
python --version  # Must be 3.10+
# Install Python 3.11+ from python.org or your package manager
```

## Runtime

### Port 8770 already in use
```bash
# Find what's using it
lsof -i :8770        # Linux/macOS
netstat -ano | findstr 8770  # Windows

# Change port
export NOUS_BRAIN_PORT=8771
```

### Runtime won't start
```bash
nous doctor          # Check environment
tail -50 ~/.config/nous/logs/nous.log  # Check logs
```

### Demo mode not working
```bash
export NOUS_DEMO_MODE=1
nous start
```

## Providers

### Connection test fails
1. Check API key is correct
2. Check endpoint URL
3. Check network: `ping api.openai.com`
4. Check firewall/proxy

### Rate limited (429)
The Runtime retries automatically with exponential backoff. If persistent:
- Check your API usage dashboard
- Consider using a different provider
- Reduce request frequency

### Provider health shows "degraded"
- Provider may be temporarily unavailable
- Check provider status page
- The Runtime will retry automatically

## Packs

### Pack install fails
```bash
nous dev validate   # Check pack.yaml
nous dev test       # Run pack tests
```

### Pack capability not found
```bash
nous capability list | grep my-pack
```

## Configuration

### Config not loading
```bash
nous doctor          # Checks write permissions
ls -la ~/.config/nous/  # Check config exists
```

### Reset configuration
```bash
rm -rf ~/.config/nous/
nous init
```

## Getting Help

1. Run `nous doctor` first
2. Check logs in `~/.config/nous/logs/`
3. Read docs in `docs/user/getting-started/`
4. Open an issue with the output of `nous doctor`

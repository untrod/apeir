# Install Nous on macOS

## Requirements
- macOS 13+ (Ventura or newer)
- Python 3.10+
- Intel or Apple Silicon
- 4GB RAM

## Quick Install

```bash
# 1. Install Python
brew install python@3.11

# 2. Install Nous
pip3 install nous-runtime[all]

# 3. Verify
nous version
nous doctor
```

## Homebrew (planned)

```bash
brew install nous-runtime
```

## First Run

```bash
nous init
nous start
nous
```

## Service

```bash
brew services start nousd    # (planned)
```

## Configuration

Config stored at `~/Library/Application Support/Nous/`

## Apple Silicon Notes

All dependencies work natively on Apple Silicon (M1/M2/M3). Use Python 3.11+ for best compatibility.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `pip` not found | `python3 -m pip install nous-runtime[all]` |
| Tesseract | `brew install tesseract` |
| Port in use | `lsof -i :8770` |

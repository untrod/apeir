# Install Nous on Linux

## Requirements
- Ubuntu 20.04+ / Debian 11+
- Python 3.10+
- 4GB RAM (8GB+ recommended)

## Quick Install

```bash
# 1. Install Python
sudo apt update && sudo apt install python3 python3-pip -y

# 2. Install Nous
pip install nous-runtime[all]

# 3. Verify
nous version
nous doctor
```

## One-Line Installer

```bash
curl -fsSL https://install.nous.ai | bash
```

## First Run

```bash
nous init        # Interactive setup wizard
nous start       # Start Runtime
nous             # Interactive shell
```

## Systemd Service

```bash
sudo cp deploy/nousd.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nousd
nous status
```

## Configuration

Config stored at `~/.config/nous/`

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Permission denied | `sudo chown -R $USER ~/.config/nous` |
| Port 8770 in use | `sudo lsof -i :8770` |
| Tesseract (OCR) | `sudo apt install tesseract-ocr` |
| Missing libs | `sudo apt install build-essential python3-dev` |

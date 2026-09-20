# Install Nous with Docker

## Requirements
- Docker 24+
- Docker Compose v2

## Quick Start

```bash
git clone <repo-url> nous-runtime
cd nous-runtime
docker compose up -d
curl http://localhost:8770/health
```

## Docker Image

```bash
docker pull nous-runtime/nous:latest
docker run -d -p 8770:8770 \
  -e NOUS_DEMO_MODE=1 \
  -v nous-data:/opt/nous/data \
  nous-runtime/nous:latest
```

## Configuration

```bash
# Copy example config
cp remote_terminal/.env.example remote_terminal/.env

# Edit with your API keys
vim remote_terminal/.env

# Start with config
docker compose up -d
```

## Access
- Runtime API: http://localhost:8770
- Health: http://localhost:8770/health
- Control Center: http://localhost:8770/control

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Port conflict | Change `ports:` in docker-compose.yml |
| Volume permissions | `chown -R 1000:1000 data/` |
| Container exits | `docker logs nous-brain` |

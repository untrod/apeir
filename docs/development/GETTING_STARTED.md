# Getting Started for Developers

## 5-Minute Setup

```bash
git clone <repo>
cd nous
cp remote_terminal/.env.example remote_terminal/.env
export NOUS_DEMO_MODE=1
python remote_terminal/brain.py
# Open http://localhost:8770/control
```

## Project Structure

```
remote_terminal/         — Brain server + Kernel
  brain.py               — HTTP server, capability wiring
  nous_core/             — Kernel modules (23 files)
  nous_edge/             — Python Edge SDK
desktop/                 — Tauri Desktop App
docs/                    — Documentation
examples/                — Runnable examples
scripts/                 — install, doctor, healthcheck
```

## Key Concepts

1. **Everything is a Capability**: `request_capability("model.reason", prompt="...")`
2. **Providers are pluggable**: Swap GPT for Claude by changing provider
3. **Risk-gated**: HIGH/CRITICAL operations require confirmation
4. **Reasoning trace**: Every decision is recorded with rationale

## Your First Provider

See `docs/development/WRITE_A_PROVIDER.md`

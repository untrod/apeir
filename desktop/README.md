# Nous Control Center — Desktop App

Tauri + React + TypeScript desktop application for Nous Brain.

## Quick Start

```bash
cd desktop
npm install
npm run tauri:dev     # Development with hot reload
npm run tauri:build   # Production build (Windows/macOS/Linux)
```

## Prerequisites

- Node.js 18+
- Rust toolchain (`curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`)
- Tauri system deps: [tauri.app/prerequisites](https://tauri.app/prerequisites)

## Architecture

```
desktop/
├── src/
│   ├── App.tsx           # Main app with 8-page router
│   ├── main.tsx          # React entry point
│   └── lib/
│       └── api.ts        # Brain API client + connection manager
├── src-tauri/
│   ├── Cargo.toml        # Rust dependencies
│   ├── tauri.conf.json   # Tauri window + security config
│   └── src/main.rs       # Rust backend entry
├── index.html
├── package.json
├── vite.config.ts
└── tsconfig.json
```

## Pages

| Page | Route | Description |
|------|-------|-------------|
| Connect | `/connect` | Brain URL + Token setup |
| Overview | `/` | Dashboard with stats, events, notifications |
| Jobs | `/jobs` | Running + failed job queues |
| Devices | `/devices` | Device registry with online status |
| Security | `/security` | Risk panel, approval queue, audit log |
| Learning | `/learning` | Daily plan, weakness, reports |
| Capabilities | `/capabilities` | Capability registry |
| Files | `/files` | Document upload + RAG status |

## Build Targets

```bash
npm run tauri:build          # Current platform
npm run tauri:build -- --target x86_64-pc-windows-msvc
npm run tauri:build -- --target x86_64-apple-darwin
npm run tauri:build -- --target x86_64-unknown-linux-gnu
```

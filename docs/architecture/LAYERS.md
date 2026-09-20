# Nous Architecture Layers

```
apps/           — Desktop App (Tauri), Phone App (Android), Watch App, Web
sdk/            — nous_edge (Python), nous-web (JS), nous-esp32 (C)
protocols/      — NKP, NEP, NFP, NSP message definitions
runtime/        — nous_core/: Kernel services (events, jobs, devices, ...)
modules/        — Learning, Notification, ModelRouter, Device
providers/      — GPT, Claude, DeepSeek, PC Agent, Phone Agent, ESP32
storage/        — SQLite (nous_core.db), ChromaDB (vectors), Files
```

## Module vs Provider

| | Module | Provider |
|---|--------|----------|
| What | Business logic | External capability |
| Examples | Learning, Capture | GPT, PC Agent, ESP32 |
| Interface | Events + Capabilities | list_capabilities, invoke, health |
| Permission | Declared in manifest | Declared by capability |

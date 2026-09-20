# Nous Architecture v1.0

## Layers

```
┌─────────────────────────────────────────┐
│  Entry Points                            │
│  Desktop App / Phone App / Watch / Web   │
├─────────────────────────────────────────┤
│  Protocol Layer (NKP / NEP / NFP / NSP) │
├─────────────────────────────────────────┤
│  Capability OS                           │
│  Registry -> Router -> Graph -> Observer   │
├─────────────────────────────────────────┤
│  Kernel Services                         │
│  Events / Jobs / Devices / Notifications │
│  Automation / Audit / Security           │
├─────────────────────────────────────────┤
│  Learning Engine                         │
│  State / Plan / Review / Sessions        │
├─────────────────────────────────────────┤
│  Provider Layer                          │
│  GPT / Claude / DeepSeek / PC / Phone    │
├─────────────────────────────────────────┤
│  Storage                                 │
│  SQLite / ChromaDB / File System         │
└─────────────────────────────────────────┘
```

## Key Design Decisions

1. **Capability-based**: Every action is `request_capability(name, params)`, not a direct function call
2. **Provider abstraction**: Models, devices, tools are all providers implementing the same interface
3. **Risk-gated**: LOW->auto, MEDIUM->audit, HIGH->confirm, CRITICAL->revoke
4. **Reasoning trace**: Every decision records WHY, not just WHAT
5. **Edge-native**: NEP protocol for ESP32, STM32, Jetson from day one
6. **Runtime Neutrality**: The Runtime contains no personal or domain-specific knowledge. All domain knowledge is provided via pluggable Providers (Study Pack, Knowledge Pack, Language Pack, etc.)

## Data Flow

```
User Input -> Router -> Capability -> Provider -> Observer -> Trace -> Audit
                                   ↓
                              Risk Gate (HIGH/CRITICAL)
                                   ↓
                              Approval Required
```

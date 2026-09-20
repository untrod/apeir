# Control Center Specification v1.0

## Purpose

The Control Center is the web-based operating console for the Nous Runtime. It provides visibility into every aspect of the running system.

## Pages

### 1. Home / Overview
- Runtime status (running/degraded/stopped)
- Provider count + health summary
- Capability count
- Pack count
- Recent jobs
- Quick actions: Start/Stop Runtime

### 2. Execution
- Live job list with status
- Task graph visualization
- Execution timeline
- Trace viewer (click to expand each step)

### 3. Capabilities
- Full capability registry
- Filter by category/provider
- Risk level indicators
- Execute capability (test console)

### 4. Providers
- Provider list with health status
- Latency and cost metrics
- Connect/Disconnect controls
- Provider detail (capabilities, health history)

### 5. Packs
- Installed packs list
- Install from directory
- Enable/Disable toggle
- Pack capabilities and dependencies

### 6. Security
- Audit log viewer
- Active approvals (pending confirmations)
- Permission matrix
- Rate limit status

### 7. Observability
- Event stream (live)
- Job statistics
- Provider performance charts
- Error rate trends

### 8. Settings
- Runtime configuration
- Provider configuration
- Pack configuration
- Log level

## Data Source

ALL pages call the same Runtime API:
```
/api/v1/kernel/health
/api/v1/kernel/capabilities
/api/v1/kernel/providers
/api/v1/kernel/jobs
/capability/request
/traces/recent
```

No page maintains its own state. No page has its own database.

## Technology

- Current: Tauri + React + TypeScript (`desktop/`)
- Future: Could be a standalone React SPA, Electron app, or Tauri app
- API client: uses the same endpoints as the Python SDK

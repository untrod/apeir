# Nous Runtime — Kernel Module Map v2

> Date: 2026-07-27
> Baseline: kernel/unified-model-runtime branch
> Purpose: Map every existing module against the master plan's 10-Batch architecture

---

## Module Inventory (by nous_runtime/ subpackage)

### kernel/
| File | Status | Maps to Batch |
|------|--------|---------------|
| `__init__.py` | Keep | 1 |
| `config.py` | Refactor — merge with remote_terminal/config.py | 1 |
| `runtime.py` | Keep — needs state machine transitions | 1 |
| `tracing.py` | Keep | 1 |
| `object_model.py` | **Expand** — current partial, needs full NousObject | 1 |

### provider/
| File | Status | Maps to Batch |
|------|--------|---------------|
| `__init__.py` | Keep | 4 |
| `base.py` | Keep | 4 |
| `registry.py` | Keep — add health aggregation | 4 |
| `router.py` | Keep | 4,7 |
| `adapters/openai.py` | Keep | 4 |
| `adapters/embed.py` | Keep | 4 |
| `adapters/audio.py` | Refactor — remove direct brain.py import | 4 |
| `adapters/chromadb.py` | Keep | 4 |
| `adapters/device_pc.py` | Refactor — remove direct brain.py import | 4,9 |
| `adapters/device_android.py` | Keep | 4,9 |
| `adapters/notification.py` | Keep | 4 |
| `adapters/web.py` | Keep | 4 |
| **Missing** | Anthropic adapter, Ollama, llama.cpp, vLLM | 4 |

### intelligence/
| File | Status | Maps to Batch |
|------|--------|---------------|
| `__init__.py` | Keep | 7 |
| `registry.py` | Keep | 7 |
| `policy_loader.py` | Keep | 7 |
| `explanation.py` | Keep | 7 |
| `evaluator.py` | Keep | 7 |
| `history.py` | Keep | 6 |
| `cache.py` | Keep | 7 |
| `consistency.py` | Keep | 7 |
| `replay.py` | Keep | 8 |
| `policies/base.py` | Keep | 7 |
| `policies/static.py` | Keep | 7 |
| `policies/composite.py` | Keep | 7 |
| `policies/fallback.py` | Keep | 7 |
| `policies/override.py` | Keep | 7 |
| `policies/rule.py` | Keep | 7 |
| `decisions/provider.py` | Keep | 7 |
| `decisions/retrieval.py` | Keep | 7 |
| `decisions/recovery.py` | Keep | 7 |
| `profiles/discovery.py` | Keep | 6 |
| `profiles/models.py` | Keep | 6 |
| `profiles/probes.py` | Keep | 6 |
| `profiles/observations.py` | Keep | 6 |
| `profiles/mapping.py` | Keep | 6 |
| `profiles/freshness.py` | Keep | 6 |
| `profiles/store.py` | Keep | 6 |
| `reliability/classifier.py` | Keep | 7 |
| `reliability/models.py` | Keep | 7 |
| `reliability/retry.py` | Keep | 7 |
| `reliability/circuit_breaker.py` | Keep | 7 |
| `reliability/fallback.py` | Keep | 7 |
| `reliability/store.py` | Keep | 7 |
| `reliability/fault_injection.py` | Keep | 7 |
| **Missing** | Task Fingerprint, Cost Estimator, Joint Scheduler | 7 |

### connectivity/
| File | Status | Maps to Batch |
|------|--------|---------------|
| `__init__.py` | Keep | 2 |
| `protocol/__init__.py` | Keep | 2 |
| `protocol/serialization.py` | Keep | 2 |
| `protocol/envelope.py` | Keep | 2 |
| `protocol/task.py` | Keep | 2 |
| `protocol/session.py` | Keep | 2 |
| `protocol/pairing.py` | Keep | 2 |
| `protocol/identity.py` | Keep | 2 |
| `protocol/heartbeat.py` | Keep | 2 |
| `protocol/error.py` | Keep | 2 |
| `control_plane/__init__.py` | Keep | 2 |
| `control_plane/gateway.py` | Keep | 2 |
| `control_plane/linkage.py` | Keep | 2 |
| `control_plane/pairing_service.py` | Keep | 2 |
| `control_plane/session_registry.py` | Keep | 2 |
| `control_plane/node_registry.py` | Keep | 2 |
| `node/__init__.py` | Keep — needs full state machine | 2 |
| `cli/__init__.py` | Keep | 2 |
| `cli/commands.py` | Keep | 2 |
| `project/__init__.py` | Keep | 2 |
| **Missing** | Full offline recovery (5-state), Lease, Checkpoint, Event Replay, Message Dedup | 2 |

### retrieval/
| File | Status | Maps to Batch |
|------|--------|---------------|
| All files | Keep — mature subsystem | 3 |
| **Missing** | — | — |

### planner/
| File | Status | Maps to Batch |
|------|--------|---------------|
| `__init__.py` | Keep | 8 |
| `graph.py` | Keep | 8 |
| `pipeline.py` | Keep | 8 |
| `scheduler.py` | Keep | 8 |
| `evaluator.py` | Keep | 8 |
| `tool_router.py` | Keep | 5,8 |
| `observation.py` | Keep | 8 |
| `dispatcher.py` | Keep | 8 |
| **Missing** | Formal PlanArtifact, ExecutionTicket | 5 |

### capability/
| File | Status | Maps to Batch |
|------|--------|---------------|
| `__init__.py` | Keep | 5 |
| `lifecycle.py` | Keep | 5 |
| `manifest.py` | Keep | 5 |
| `resolver.py` | Keep | 5 |
| `availability.py` | **New** — capability availability tracking | 5 |
| **Missing** | Full Capability Contract (risk/timeout/retry/idempotent/rollback/verify/audit), Sandbox | 5 |

### agent/
| File | Status | Maps to Batch |
|------|--------|---------------|
| `__init__.py` | Keep | 8 |
| `models.py` | Keep | 8 |
| `registry.py` | Keep | 8 |
| `runtime.py` | Keep | 8 |
| `budget.py` | Keep | 8 |
| `checkpoint.py` | Keep | 8 |
| `execution_state.py` | Keep | 8 |
| `invocation.py` | Keep | 8 |
| `termination.py` | Keep | 8 |
| `collaboration.py` | Keep | 8 |
| **Missing** | Reviewer Agent, Verifier Agent formalization | 8 |

### context/
| File | Status | Maps to Batch |
|------|--------|---------------|
| `__init__.py` | Keep | 3 |
| `builder.py` | Keep | 3 |
| `models.py` | Keep | 3 |
| `providers/__init__.py` | Keep | 3 |
| `providers/device.py` | Keep | 3 |
| `resolver.py` | Keep | 3 |
| `security.py` | Keep | 3 |
| `store.py` | Keep | 3 |
| `snapshot.py` | **New** — context snapshots | 3 |
| **Missing** | Token estimator, Auto-summary, Incremental summary | 3 |

### NEW MODULES (not in v1 KERNEL_MODULE_MAP)

### state/
| File | Maps to Batch | Notes |
|------|---------------|-------|
| `__init__.py` + `ownership.py` | 0 | State ownership tracking — architecture governance |

### evaluation/
| Files | Maps to Batch | Notes |
|-------|---------------|-------|
| `criteria.py`, `validators/`, `scoring.py`, `models.py`, `regression.py` | 6 | Model evaluation framework |
| `benchmark_runtime/` | 6 | Benchmark execution runtime |

### experience/
| Files | Maps to Batch | Notes |
|-------|---------------|-------|
| `store.py`, `collector.py`, `models.py`, `pattern.py`, `security.py` | 6 | Experience/evidence collection |

### security/
| Files | Maps to Batch | Notes |
|-------|---------------|-------|
| `__init__.py` | 5,18 | Security policy enforcement |

### services/
| Files | Maps to Batch | Notes |
|-------|---------------|-------|
| `lifecycle.py`, `jobs.py`, `events.py`, `database.py`, `traces.py` | 1 | Service abstraction for Server Primary |

### model_runtime/
| Files | Maps to Batch | Notes |
|-------|---------------|-------|
| `registry.py`, `gateway.py`, `router.py`, `adapters.py`, `configuration.py`, `distribution.py`, `resources.py`, `errors.py` | 4 | Unified model runtime — overlaps with provider/ |

### workspace/
| Files | Maps to Batch | Notes |
|-------|---------------|-------|
| `registry.py` | 2 | Workspace management for Worker nodes |

### artifact/
| Files | Maps to Batch | Notes |
|-------|---------------|-------|
| `registry.py` | 5 | Artifact registry — foundation for PlanArtifact |

### plugins/
| Files | Maps to Batch | Notes |
|-------|---------------|-------|
| `registry.py` | 4 | Plugin system for Provider extensibility |

### deployment/
| Files | Maps to Batch | Notes |
|-------|---------------|-------|
| `setup_wizard.py` | 10 | Bootstrap wizard |

### network/
| Files | Maps to Batch | Notes |
|-------|---------------|-------|
| `registry.py` | 2 | Network transport abstraction |

### marketplace/
| Files | Maps to Batch | Notes |
|-------|---------------|-------|
| `registry.py` | 10 | Provider/Agent marketplace (future) |

### ecosystem/
| Files | Maps to Batch | Notes |
|-------|---------------|-------|
| `registry.py` | 4 | Ecosystem-wide capability registry |

### verification/
| Files | Maps to Batch | Notes |
|-------|---------------|-------|
| `runtime.py`, `verifiers.py`, `errors.py` | 5,8 | Verification runtime for task validation |

### core/
| Files | Maps to Batch | Notes |
|-------|---------------|-------|
| `errors.py` | 1 | Unified error codes |

### sdk/
| Files | Maps to Batch | Notes |
|-------|---------------|-------|
| `client.py`, `advanced.py` | 10 | Python SDK for external consumers |

---

## Duplicate / Overlapping Modules

| Pattern | Files | Recommendation |
|---------|-------|----------------|
| **Dual Model registries** | `model_runtime/registry.py` + `model/registry.py` | Merge into unified Model Registry under Batch 4 |
| **Dual Capability registries** | `ecosystem/registry.py` (CapabilityRegistry) + `capability/` (via compat) | Consolidate into capability/ module |
| **Registry pattern ×22** | 22 separate Registry classes across codebase | Apply unified Object Model (NousObject) base class |
| **Config ×3** | `kernel/config.py` + `remote_terminal/config.py` + `model_runtime/configuration.py` | Merge into single Config system |
| **Direct brain.py imports** | `audio.py`, `device_pc.py` (4 sites) | Route through compat/ or replace with native implementations |

---

## Registry Fragmentation (22 registries found)

1. `agent/registry.py` — AgentRegistry
2. `artifact/registry.py` — ArtifactRegistry
3. `workspace/registry.py` — WorkspaceRegistry
4. `model_runtime/registry.py` — ModelRuntimeRegistry
5. `model/registry.py` — ModelRegistry (duplicate of above)
6. `plugins/registry.py` — PluginRegistry
7. `retrieval/embeddings.py` — EmbeddingRegistry
8. `retrieval/registry.py` — RetrievalBackendRegistry
9. `connectivity/control_plane/session_registry.py` — SessionRegistry
10. `connectivity/control_plane/node_registry.py` — NodeRegistry
11. `model_runtime/adapters.py` — ModelAdapterRegistry
12. `pack/registry.py` — PackRegistry
13. `intelligence/scoring/registry.py` — CapabilityDimensionRegistry
14. `provider/registry.py` — ProviderRegistry
15. `network/registry.py` — NetworkRegistry
16. `marketplace/registry.py` — MarketplaceRegistry
17. `ecosystem/registry.py` — CapabilityRegistry
18. `evaluation/criteria.py` — CriteriaRegistry
19. `intelligence/registry.py` — PolicyRegistry
20. `intelligence/profiles/discovery.py` — ProviderRegistryDiscovery

**Target**: All 22 should share a common `NousObject` base with standard CRUD, ID, status, and lifecycle.

# Virtual Context Memory — v1alpha

> Status: v1alpha (experimental)
> Target: RC8
> Analogy: Virtual Memory for AI State

## Concept

Agent programs should NOT directly manage: chat history, KV cache, retrieval
results, file contents, tool outputs, summaries, embeddings, remote knowledge,
or multi-model conversion state.

They see ONE logical address space. The kernel maps logical pages to physical
storage across GPU HBM, CPU RAM, NVMe, remote object stores, semantic caches,
and recomputed state — analogous to how an OS maps virtual pages to physical RAM,
swap, and mmap'd files.

## Logical Address Space Layout

```
0x0000_0000 — System Contract (immutable, kernel-provided)
0x1000_0000 — User Goal (versioned, principal-owned)
0x2000_0000 — Conversation (versioned, append-only segments)
0x3000_0000 — Retrieved Knowledge (derived, TTL-bound)
0x4000_0000 — Tool Results (versioned, per-tool namespaces)
0x5000_0000 — Artifacts (immutable, content-addressed)
0x6000_0000 — Model KV State (derived, model-specific, recomputable)
0x7000_0000 — Working Memory (ephemeral, process-private)
0x8000_0000 — Evidence (immutable, append-only proof chain)
0x9000_0000 — Private Namespace (per-principal, encrypted)
```

## Context Page Types (10)

| Page Type | Consistency | Backing | Recomputable |
|-----------|-------------|---------|--------------|
| TokenPage | IMMUTABLE | Any storage | No (source data) |
| SemanticPage | VERSIONED | Object store | Yes (from source) |
| KVPage | DERIVED | GPU HBM, Pinned RAM | Yes (re-Prefill) |
| PrefixPage | DERIVED | GPU HBM, RAM | Yes (shared prefix) |
| RetrievalPage | VERSIONED | Object store | Yes (re-retrieve) |
| ToolResultPage | VERSIONED | Object store | Yes (re-execute) |
| ArtifactPage | IMMUTABLE | Content-addressed | No |
| SummaryPage | DERIVED | Any storage | Yes (re-summarize) |
| EvidencePage | IMMUTABLE | Journal | No (proof chain) |
| CheckpointPage | STRONG | Journal + storage | No |

## Page Descriptor

```
ContextPage {
    page_id: uint64,              // Logical address
    page_type: ContextPageType,
    content_hash: SHA256,
    schema: string,               // Content schema URI
    model_compatibility: string[],// Models that can consume this page
    namespace: string,
    data_classification: PUBLIC | INTERNAL | CONFIDENTIAL | RESTRICTED,
    permissions: { read, write, share },
    provenance: ProvenanceChain,  // How this page was created
    version: uint64,
    invalidation_conditions: Condition[],  // When this page becomes stale
    reuse_probability: float,     // 0.0–1.0, updated by scheduler
    recompute_cost_us: uint64,    // Time to regenerate
    load_cost_us: uint64,         // Time to load from backing store
    quality_risk: float,          // Risk of quality loss if using derived version
    current_location: PhysicalLocation,
}
```

## Physical Backing Store

```
PhysicalLocation {
    tier: HBM | PinnedRAM | NormalRAM | NVMe | Remote | ObjectStore,
    device_id: string | null,
    node_id: string,
    size_bytes: uint64,
    last_access_us: uint64,
    access_count: uint64,
}
```

## Page Fault Handler

```
fn handle_page_fault(process, logical_address) → ContextPage:
    1. Check permissions (process.capability_set vs page.permissions)
    2. Search local backing stores (HBM → RAM → NVMe)
    3. Search semantic equivalents (same content_hash, different representation)
    4. Remote load (from object store or peer node)
    5. Recompute (if recomputable and cost acceptable)
    6. Summary fallback (if quality budget allows degraded representation)
    7. Model conversion (translate page to target model format)
    8. Return error (unrecoverable)
```

## Consistency Model

| Level | Description | Use Case |
|-------|-------------|----------|
| STRONG | Read always returns latest write | Approval results, effect receipts |
| VERSIONED | Reads return a specific version | File snapshots, tool results |
| EVENTUAL | Reads may be stale | Embeddings, cached summaries |
| IMMUTABLE | Never changes after creation | Artifacts, evidence, source data |
| DERIVED | Can be regenerated from source | KV cache, summaries, embeddings |
| EPHEMERAL | Lost on process termination | Working memory, scratch space |

## Context Pager Interface

```
trait ContextPager {
    // Map a logical page into physical memory
    fn map(process_id, logical_address, required_consistency) → Result<PhysicalLocation>;

    // Prefetch pages likely to be accessed soon
    fn prefetch(process_id, logical_addresses: [uint64]);

    // Evict pages under memory pressure
    fn evict(process_id, logical_addresses: [uint64], target_tier: StorageTier);

    // Invalidate stale pages
    fn invalidate(logical_addresses: [uint64], reason: InvalidationReason);

    // Convert page to different representation
    fn convert(logical_address, target_schema, target_model) → ContextPage;

    // Pin page (prevent eviction)
    fn pin(logical_address, duration_us: uint64);

    // Unpin page
    fn unpin(logical_address);
}
```

## Cross-Representation Mapping

A single logical page can have multiple physical representations:

```
Logical Page 0x2000_1000 ("conversation-turn-5")
├── TokenPage: ["User:", "What", "is", "AI?", ...]
├── KVPage: GPU HBM, 2.4MB, model=Qwen-7B, layer=0-31
├── SemanticPage: {intent: "definition_request", entities: ["AI"]}
├── SummaryPage: "User asked for a definition of AI."
└── EmbeddingPage: [0.123, -0.456, ...], 1536-dim
```

The scheduler chooses which representation to use based on the current model,
quality requirements, latency budget, and memory pressure.

# RFC-0007: Nous Memory Fabric

- **Status:** Draft
- **Date:** 2026-08-04
- **Depends on:** RFC-0001, RFC-0002

## Problem

There is no unified memory management across models, KV caches, tensors, and prefixes. Each engine manages its own memory independently, preventing cross-engine cache sharing, weight deduplication, and tiered storage.

## Proposed Design

Unified memory objects: WeightObject, TensorObject, KVObject, PrefixObject, EmbeddingObject, ArtifactObject, CheckpointObject.

Tiered storage: HBM/VRAM → Pinned RAM → Normal RAM → NVMe → Remote Memory → Object Storage.

V1 scope: metadata management, cache connector, offload policy. No custom attention kernels.

## Key Features

- Content addressing (hash-based lookup)
- Model weight deduplication (same weights loaded once)
- mmap/Copy-on-Write for weight sharing
- KV page table management
- Prefix cache with LRU/LFU eviction
- Multi-level eviction (VRAM→RAM→NVMe)
- Async prefetch based on access patterns
- Memory pressure signals with watermarks
- VRAM fragmentation observation
- Cross-process handle sharing via memfd/DMA-BUF

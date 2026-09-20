# RFC-0012: Model Package Standard

- **Status:** Draft | **Depends on:** RFC-0002

## Model Manifest

37 fields: identity, family, architecture, total/activated parameters, layers, hidden_size, attention type/heads/layout, KV heads, head_dim, experts (total/active/shared), context_length, RoPE params, tokenizer, modalities, vision/audio encoders, weight format/precision, activation precision, quantization, tensor shapes, kv_bytes_per_token, supported engines/devices, required operators, parallelism support, memory requirements, license, source, hashes, signature, SBOM, security status, benchmark profiles.

Must accommodate: Dense, MoE, MLA, GQA, MHA, Sparse Attention, KDA, hybrid attention, MTP, draft models, thinking budgets, multimodal encoders.

## Import Pipeline

Download→Hash Verify→Signature Verify→License Check→SBOM→Format Parse→Tensor Shape Validation→Memory Bound Validation→Operator Check→Isolated Conversion→Smoke Test→Benchmark→Quarantine/Admit.

## Blocked Formats

No pickle, no trust_remote_code, no unsigned binaries, no unknown operator loading into kernel.

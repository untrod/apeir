# RFC-0005: Engine ABI v1

- **Status:** Draft
- **Date:** 2026-08-04
- **Depends on:** RFC-0001, RFC-0002

## Problem

Engines (vLLM, llama.cpp, SGLang, ONNX Runtime, TensorRT-LLM, etc.) currently run in-process with the Python runtime. There is no stable interface for adding new engines, no process isolation, no capability negotiation, and no resource estimation contract.

## Proposed Contract

Engine ABI v1 defines 17 operations that every engine must implement: probe, capabilities, validate_model, estimate_resources, compile, load_model, warmup, infer, stream_infer, cancel, pause, snapshot, restore, drain, unload_model, health, metrics.

See `spec/engine-abi/v1/engine_abi.proto` for the full protobuf definition.

## Key Decisions

1. **Process isolation** — Engines run in `nous-modeld`, never linked into `nousd`
2. **Capability negotiation** — `probe()` returns engine capabilities; kernel adapts
3. **Version negotiation** — `abi_version` in probe response enables forward compatibility
4. **Resource estimation** — `estimate_resources()` before loading prevents OOM
5. **Streaming** — `stream_infer()` returns a token stream via gRPC server streaming
6. **Cancellation** — `cancel(request_id)` allows cooperative cancellation

## Reference Adapters

- llama.cpp (local, GGUF)
- vLLM (server, various formats)
- SGLang (server, various formats)
- ONNX Runtime (local, ONNX)
- OpenAI-compatible API (remote, HTTP)

## Validation

- Contract test: every method returns correct response type
- Isolation test: engine crash does not affect kernel
- Resource test: estimate matches actual allocation within 20%
- Compatibility test: engine claiming ABI v1 works with kernel v1 and v2

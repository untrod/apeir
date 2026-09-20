# Research Literature

Organized prior art for Nous research claims. Each entry must cite specific work and explain the specific difference from Nous.

## Organization
- `os-context-memory/` — Virtual memory, paging, context management
- `scheduling/` — ML scheduling, critical path, resource-aware scheduling
- `speculative-execution/` — Speculation, branch prediction, durable speculation
- `proof-carrying/` — PCC, attested execution, verifiable computation
- `digital-twins/` — Simulation, digital twins, what-if analysis
- `multi-agent/` — Multi-agent coordination, agent frameworks
- `llm-systems/` — LLM serving, inference engines, KV cache management
- `safe-learning/` — Safe RL, constrained optimization, online adaptation

## Format
Each paper entry:
```bibtex
@paper{key,
  title = "...",
  author = "...",
  year = ...,
  venue = "...",
  nous_difference = "How Nous differs from or extends this work",
  nous_relevance = "Which Nous module this relates to"
}
```

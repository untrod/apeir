# Prior Art Survey

Systematic comparison of Nous against related systems. Each entry must cite specific evidence of the other system's capability, not assumptions.

## Systems Surveyed

| System | Type | Key Feature | Nous Difference |
|--------|------|-------------|-----------------|
| OpenClaw | Agent Gateway | Channel-based multi-agent | Kernel-level resource management |
| LangChain/LangGraph | Agent Framework | Library-based agent composition | Runtime with process model and scheduling |
| AutoGen | Multi-Agent | Conversation-driven agents | State machine process model with checkpoint |
| CrewAI | Multi-Agent | Role-based collaboration | Resource-aware scheduling |
| vLLM | Inference Engine | PagedAttention KV cache | Cross-representation context paging |
| SGLang | Inference Engine | RadixAttention prefix caching | Context VM beyond token caching |
| Letta/MemGPT | Memory Management | OS-inspired LLM memory | Full context address space with page types |
| Dify/Coze | LLM App Platform | Visual workflow builder | Kernel with governance and effect gating |
| Kubernetes | Container Orchestration | Pod scheduling, DRA | Agent-aware scheduling with model placement |

## Claims Requiring Validation

For each Nous claim of novelty, we must:
1. Identify the closest prior system
2. Document what that system actually does (not what we assume)
3. Specify the exact difference
4. Design an experiment to validate the difference matters

禁止仅凭"没有发现相同项目"宣称原创。

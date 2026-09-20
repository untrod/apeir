# Research Hypotheses

Falsifiable claims with pre-registered predictions. Each hypothesis must include:
- Research question
- Prior work
- Nous-specific claim
- Falsification condition
- Baseline
- Experiment design
- Ablation plan
- Success criteria

## Active Hypotheses

### H1: Context VM reduces token usage vs full history
- **Claim:** Cross-representation context paging reduces total tokens by 30%+ vs full history retransmission for long-running agent tasks (>100 turns)
- **Falsification:** If paging overhead exceeds savings, or if quality degrades beyond acceptable threshold
- **Baseline:** Full history retransmission, RAG-based retrieval, prefix caching
- **Status:** UNVERIFIED — pager backends all stubbed

### H2: State-aware scheduling improves task completion rate
- **Claim:** State-Aware Critical-Path Scheduling (P_i formula) improves long-task completion rate by 15%+ vs FIFO
- **Falsification:** If warm-state transfer cost is negligible in practice
- **Baseline:** FIFO, Priority, Cache-Aware
- **Status:** RESEARCH — P_i formula marked "RESEARCH hypothesis" in code

### H3: Durable speculation reduces effective latency
- **Claim:** Journal-backed speculative execution reduces P95 latency by 20%+ for multi-step agent tasks
- **Falsification:** If speculation rollback cost exceeds benefit in >30% of cases
- **Baseline:** Sequential execution with per-step journal
- **Status:** UNVERIFIED — no journal integration

### H4: Proof-carrying execution prevents side-effect duplication
- **Claim:** Canonical action binding prevents all replay attacks on agent side effects
- **Falsification:** Any successful replay of a committed action with modified parameters
- **Baseline:** Idempotency keys, approval replay detection
- **Status:** UNVERIFIED — attestation always None

### H5: Digital twin scheduling outperforms static placement
- **Claim:** EMA-updated digital twin reduces scheduling failures by 25%+ vs static weighted-sum placement
- **Falsification:** If twin predictions are less accurate than static heuristics
- **Baseline:** WeightedSumPolicy, CacheAwarePolicy
- **Status:** UNVERIFIED — record_outcome never called

### H6: Pareto multi-objective routing beats single-score
- **Claim:** Multi-objective Pareto routing (cost × quality × latency) improves verified task outcomes vs weighted scalar
- **Falsification:** If Pareto frontier offers no practical benefit over tuned scalar weights
- **Baseline:** WeightedSumPolicy
- **Status:** PARTIAL — Pareto router exists, no experimental comparison

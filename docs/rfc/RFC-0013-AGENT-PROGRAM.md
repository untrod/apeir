# RFC-0013: Agent Program Compiler

- **Status:** Draft | **Depends on:** RFC-0003

## Problem

Agent and workflow execution is currently hard-coded in Python (`WorkflowRuntime`, `AgentExecutionRuntime`). There is no unified compilation from agent definition to executable graph.

## AgentExecutionGraph

Compiler analyzes: data dependencies, control dependencies, tool dependencies, cache reuse, KV reuse, critical path, parallelizable steps, mergeable model calls, small-model-suitable steps, strong-model-required steps, verification boundaries, human approval boundaries, compensation, checkpoint.

## Scheduling

Scheduling object must be the complete Agent Program, not individual API calls. Critical path nodes that unlock many downstream tasks should be prioritized.

## Quality

Multi-agent is not inherently better than single-agent. Must compare under same tools, budget, output contract, and evaluation protocol. Report quality, cost, and failure rate — not agent count.

## Compiler Phases

Parse agent definition → Build dependency graph → Identify parallel regions → Insert verification nodes → Insert checkpoint nodes → Estimate resources per step → Output AgentExecutionGraph.

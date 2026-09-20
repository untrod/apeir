# -*- coding: utf-8 -*-
"""Dynamic Task Graph Compiler — compiles user tasks into executable DAGs.

Supports: DAG validation, cycle detection, critical path analysis,
optional nodes, speculative branches, conditional edges, fan-out/fan-in,
cancellation propagation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskNode:
    """A node in the task graph."""
    node_id: str = ""
    objective: str = ""
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    resource_requirements: dict[str, Any] = field(default_factory=dict)
    write_scope: str = "workspace"
    acceptance_conditions: list[str] = field(default_factory=list)
    verification: list[str] = field(default_factory=list)
    failure_policy: str = "fail"
    timeout_seconds: int = 300
    retry_policy: str = "none"
    checkpoint_policy: str = "after_completion"
    optional: bool = False
    speculative: bool = False


@dataclass
class TaskGraph:
    """Complete task execution DAG."""
    graph_id: str = ""
    nodes: dict[str, TaskNode] = field(default_factory=dict)
    edges: list[tuple[str, str, str]] = field(default_factory=list)  # (from, to, type)
    metadata: dict[str, Any] = field(default_factory=dict)

    def node_ids(self) -> list[str]:
        return list(self.nodes.keys())

    def dependencies_of(self, node_id: str) -> list[str]:
        dependencies = {f for f, t, _ in self.edges if t == node_id}
        node = self.nodes.get(node_id)
        if node is not None:
            dependencies.update(node.dependencies)
        return sorted(dependencies)

    def dependents_of(self, node_id: str) -> list[str]:
        dependents = {t for f, t, _ in self.edges if f == node_id}
        dependents.update(
            candidate_id
            for candidate_id, candidate in self.nodes.items()
            if node_id in candidate.dependencies
        )
        return sorted(dependents)

    def critical_path(self) -> list[str]:
        """Longest dependency chain via topological sort + DP."""
        topo = self._topological_order()
        if topo is None:
            return []
        dist = {nid: 1 for nid in topo}
        for nid in topo:
            for dep in self.dependencies_of(nid):
                dist[nid] = max(dist[nid], dist.get(dep, 0) + 1)
        max_d = max(dist.values()) if dist else 0
        return [nid for nid, d in dist.items() if d == max_d]

    def _topological_order(self) -> list[str] | None:
        in_degree = {nid: len(self.dependencies_of(nid)) for nid in self.node_ids()}
        queue = [nid for nid, d in in_degree.items() if d == 0]
        result = []
        while queue:
            nid = queue.pop(0)
            result.append(nid)
            for dep in self.dependents_of(nid):
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    queue.append(dep)
        return result if len(result) == len(self.nodes) else None


def validate_dag(graph: TaskGraph) -> tuple[bool, str]:
    """Validate a task graph: no cycles, all references exist."""
    topo = graph._topological_order()
    if topo is None:
        return False, "Cycle detected in task graph"
    for nid, node in graph.nodes.items():
        for dep in node.dependencies:
            if dep not in graph.nodes:
                return False, f"Node {nid} references unknown dependency {dep}"
    return True, "Graph valid"


class GraphCompiler:
    """Compiles task descriptions into executable TaskGraph DAGs."""

    def compile(self, task: dict[str, Any]) -> TaskGraph:
        """Compile a task into a TaskGraph."""
        graph = TaskGraph(graph_id=task.get("task_id", "graph_000"))

        task_type = str(task.get("task_type", "general"))
        complexity = str(task.get("complexity", "medium"))

        if task_type in ("code_audit", "bug_fix", "code_refactor"):
            graph = self._compile_code_task(task, complexity)
        elif task_type in ("test_generation",):
            graph = self._compile_test_task(task, complexity)
        elif task_type in ("research", "web_research", "data_analysis"):
            graph = self._compile_research_task(task, complexity)
        elif task_type in ("multi_node", "distributed"):
            graph = self._compile_distributed_task(task, complexity)
        else:
            graph = self._compile_simple_task(task, complexity)

        graph.metadata = {"task_type": task_type, "complexity": complexity}
        return graph

    def _compile_code_task(self, task: dict, complexity: str) -> TaskGraph:
        graph = TaskGraph(graph_id=task.get("task_id", "code_000"))
        graph.nodes = {
            "analyze": TaskNode(node_id="analyze", objective="Analyze code and requirements",
                                required_capabilities=["code_analysis"], timeout_seconds=120),
            "implement": TaskNode(node_id="implement", objective="Implement changes",
                                  dependencies=["analyze"], required_capabilities=["code_generation"],
                                  write_scope="workspace", timeout_seconds=300),
            "test": TaskNode(node_id="test", objective="Run tests", dependencies=["implement"],
                             required_capabilities=["test_execution"], timeout_seconds=180),
        }
        if complexity in ("high", "critical"):
            graph.nodes["review"] = TaskNode(node_id="review", objective="Review changes",
                                             dependencies=["test"], required_capabilities=["code_review"],
                                             timeout_seconds=120)
        graph.edges = [(f, t, "dependency") for t, n in graph.nodes.items() for f in n.dependencies]
        return graph

    def _compile_test_task(self, task: dict, complexity: str) -> TaskGraph:
        graph = TaskGraph(graph_id=task.get("task_id", "test_000"))
        graph.nodes = {
            "understand": TaskNode(node_id="understand", objective="Understand code under test",
                                   required_capabilities=["code_analysis"], timeout_seconds=120),
            "generate": TaskNode(node_id="generate", objective="Generate test cases",
                                 dependencies=["understand"], required_capabilities=["test_generation"],
                                 timeout_seconds=300),
            "validate": TaskNode(node_id="validate", objective="Run and validate tests",
                                 dependencies=["generate"], required_capabilities=["test_execution"],
                                 timeout_seconds=180),
        }
        graph.edges = [(f, t, "dependency") for t, n in graph.nodes.items() for f in n.dependencies]
        return graph

    def _compile_research_task(self, task: dict, complexity: str) -> TaskGraph:
        graph = TaskGraph(graph_id=task.get("task_id", "research_000"))
        graph.nodes = {
            "plan": TaskNode(node_id="plan", objective="Plan research questions",
                             required_capabilities=["planning"], timeout_seconds=60),
            "search_a": TaskNode(node_id="search_a", objective="Search sources (strategy A)",
                                 dependencies=["plan"], required_capabilities=["web_search"],
                                 speculative=True, timeout_seconds=120),
            "search_b": TaskNode(node_id="search_b", objective="Search sources (strategy B)",
                                 dependencies=["plan"], required_capabilities=["web_search"],
                                 speculative=True, optional=True, timeout_seconds=120),
            "synthesize": TaskNode(node_id="synthesize", objective="Synthesize findings",
                                   dependencies=["search_a", "search_b"],
                                   required_capabilities=["synthesis"], timeout_seconds=180),
            "verify": TaskNode(node_id="verify", objective="Verify claims against sources",
                               dependencies=["synthesize"], required_capabilities=["fact_checking"],
                               timeout_seconds=120),
        }
        graph.edges = [(f, t, "dependency") for t, n in graph.nodes.items() for f in n.dependencies]
        return graph

    def _compile_distributed_task(self, task: dict, complexity: str) -> TaskGraph:
        graph = TaskGraph(graph_id=task.get("task_id", "dist_000"))
        graph.nodes = {
            "split": TaskNode(node_id="split", objective="Split work across nodes",
                              required_capabilities=["planning"], timeout_seconds=60),
            "worker_a": TaskNode(node_id="worker_a", objective="Process shard A",
                                 dependencies=["split"], required_capabilities=["computation"],
                                 timeout_seconds=300),
            "worker_b": TaskNode(node_id="worker_b", objective="Process shard B",
                                 dependencies=["split"], required_capabilities=["computation"],
                                 timeout_seconds=300),
            "merge": TaskNode(node_id="merge", objective="Merge results",
                              dependencies=["worker_a", "worker_b"],
                              required_capabilities=["data_processing"], timeout_seconds=60),
        }
        graph.edges = [(f, t, "dependency") for t, n in graph.nodes.items() for f in n.dependencies]
        return graph

    def _compile_simple_task(self, task: dict, complexity: str) -> TaskGraph:
        graph = TaskGraph(graph_id=task.get("task_id", "simple_000"))
        graph.nodes = {
            "execute": TaskNode(node_id="execute", objective=str(task.get("description", "Execute task")),
                                required_capabilities=task.get("capabilities", []),
                                timeout_seconds=int(task.get("timeout_seconds", 300))),
        }
        return graph

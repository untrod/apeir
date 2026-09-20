# -*- coding: utf-8 -*-
"""Task Graph — dependency-aware execution graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nous_runtime.planner.plan import Task, TaskStatus


@dataclass
class ExecutionNode:
    """A node in the execution graph."""
    task: Task
    children: list[ExecutionNode] = field(default_factory=list)
    level: int = 0

    @property
    def task_id(self) -> str:
        return self.task.task_id

    @property
    def is_leaf(self) -> bool:
        return len(self.children) == 0


class TaskGraph:
    """
    A directed acyclic graph (DAG) of tasks with dependency edges.

    Supports:
    - Sequential execution: A → B → C
    - Parallel execution: A, B → C
    - Mixed: A → B, A → C → D
    - Failure handling: skip downstream on failure
    """

    def __init__(self):
        self.nodes: dict[str, ExecutionNode] = {}

    def build(self, tasks: list[Task]) -> list[ExecutionNode]:
        """Build the execution graph from a task list."""
        self.nodes = {}
        # Create nodes
        for t in tasks:
            self.nodes[t.task_id] = ExecutionNode(task=t)

        # Build dependency edges
        for t in tasks:
            for dep_id in t.depends_on:
                if dep_id in self.nodes:
                    self.nodes[dep_id].children.append(self.nodes[t.task_id])

        # Compute levels (BFS from roots)
        roots = [n for n in self.nodes.values() if not n.task.depends_on]
        for root in roots:
            self._compute_levels(root, 0)

        return roots

    def _compute_levels(self, node: ExecutionNode, level: int) -> None:
        node.level = level
        for child in node.children:
            self._compute_levels(child, level + 1)

    def roots(self) -> list[ExecutionNode]:
        """Nodes with no incoming dependencies."""
        return [n for n in self.nodes.values() if not n.task.depends_on]

    def leaves(self) -> list[ExecutionNode]:
        """Nodes with no outgoing dependencies."""
        return [n for n in self.nodes.values() if n.is_leaf]

    def ready_nodes(self, completed: set[str]) -> list[ExecutionNode]:
        """Nodes whose dependencies are all satisfied."""
        ready = []
        for n in self.nodes.values():
            if n.task.status == TaskStatus.PENDING:
                if n.task.is_ready(completed):
                    ready.append(n)
        return ready

    def level_order(self) -> list[list[ExecutionNode]]:
        """Return nodes grouped by level for parallel execution."""
        max_level = max((n.level for n in self.nodes.values()), default=0)
        levels: list[list[ExecutionNode]] = [[] for _ in range(max_level + 1)]
        for n in self.nodes.values():
            levels[n.level].append(n)
        return levels

    def is_complete(self) -> bool:
        return all(n.task.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED, TaskStatus.FAILED)
                   for n in self.nodes.values())

    def summary(self) -> dict[str, Any]:
        roots = [n.task_id for n in self.roots()]
        leaves = [n.task_id for n in self.leaves()]
        levels = self.level_order()
        return {
            "total_nodes": len(self.nodes),
            "roots": roots,
            "leaves": leaves,
            "depth": len(levels),
            "by_level": [[n.task_id for n in lvl] for lvl in levels],
        }

    def to_mermaid(self) -> str:
        """Render as Mermaid flowchart."""
        lines = ["graph TD"]
        for n in self.nodes.values():
            tid = n.task_id[-8:]
            desc = n.task.description[:30]
            lines.append(f"    {tid}[\"{desc}\"]")
            for child in n.children:
                cid = child.task_id[-8:]
                lines.append(f"    {tid} --> {cid}")
        return "\n".join(lines)

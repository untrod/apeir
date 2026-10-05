"""Durable resource graph using the existing atomic JSON state pattern."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from nous_runtime.capability.contract import CapabilityContract
from nous_runtime.connectivity.protocol.identity import NodeIdentity
from nous_runtime.planner.observation import Observation
from nous_runtime.reality.contracts import (
    Device,
    RelationKind,
    Resource,
    ResourceKind,
    ResourceRelation,
    Transport,
    Operation,
)


class ResourceGraph:
    """Small persistent adjacency set, intentionally not a graph database."""

    def __init__(self, state_dir: str | Path):
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.path = self.state_dir / "reality-resource-graph.json"
        self._resources: dict[str, Resource] = {}
        self._relations: dict[str, ResourceRelation] = {}
        self._load()

    def put(self, resource: Resource) -> Resource:
        self._resources[resource.resource_id] = resource
        self._save()
        return resource

    def add_node(self, node: NodeIdentity) -> Resource:
        return self.put(Resource(node.node_id, ResourceKind.NODE, node.to_dict()))

    def add_device(self, device: Device) -> Resource:
        return self.put(
            Resource(device.device_id, ResourceKind.DEVICE, device.to_dict())
        )

    def add_capability(self, capability: CapabilityContract) -> Resource:
        return self.put(
            Resource(
                capability.capability_id, ResourceKind.CAPABILITY, capability.to_dict()
            )
        )

    def add_transport(self, transport: Transport) -> Resource:
        return self.put(
            Resource(
                transport.transport_id, ResourceKind.TRANSPORT, transport.to_dict()
            )
        )

    def add_observation(self, observation: Observation) -> Resource:
        return self.put(
            Resource(
                observation.observation_id,
                ResourceKind.OBSERVATION,
                observation.to_dict(),
            )
        )

    def add_operation(self, operation: Operation) -> Resource:
        return self.put(
            Resource(
                operation.operation_id, ResourceKind.OPERATION, operation.to_dict()
            )
        )

    def get(self, resource_id: str) -> Resource | None:
        return self._resources.get(resource_id)

    def list(self, kind: ResourceKind | None = None) -> tuple[Resource, ...]:
        values = self._resources.values()
        if kind is not None:
            values = (item for item in values if item.kind is kind)
        return tuple(sorted(values, key=lambda item: item.resource_id))

    def relate(
        self,
        source_id: str,
        relation: RelationKind,
        target_id: str,
        *,
        attributes: Mapping[str, Any] | None = None,
    ) -> ResourceRelation:
        source = self.get(source_id)
        target = self.get(target_id)
        if source is None or target is None:
            raise ValueError("both relation endpoints must exist")
        _validate_relation(source.kind, relation, target.kind)
        edge = ResourceRelation(source_id, relation, target_id, attributes or {})
        self._relations[edge.relation_id] = edge
        self._save()
        return edge

    def relations(
        self,
        *,
        resource_id: str = "",
        relation: RelationKind | None = None,
    ) -> tuple[ResourceRelation, ...]:
        values = self._relations.values()
        if resource_id:
            values = (
                item
                for item in values
                if resource_id in {item.source_id, item.target_id}
            )
        if relation is not None:
            values = (item for item in values if item.relation is relation)
        return tuple(sorted(values, key=lambda item: item.relation_id))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "apeir.reality-resource-graph/v1alpha1",
            "resources": [item.to_dict() for item in self.list()],
            "relations": [item.to_dict() for item in self.relations()],
        }

    def _load(self) -> None:
        if not self.path.is_file():
            return
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("resource graph state must be a JSON object")
        self._resources = {
            item.resource_id: item
            for item in (Resource.from_dict(raw) for raw in value.get("resources", ()))
        }
        self._relations = {}
        for raw in value.get("relations", ()):
            edge = ResourceRelation(
                source_id=str(raw.get("source_id") or ""),
                relation=RelationKind(str(raw.get("relation") or "")),
                target_id=str(raw.get("target_id") or ""),
                attributes=dict(raw.get("attributes") or {}),
            )
            _validate_relation(
                self._resources[edge.source_id].kind,
                edge.relation,
                self._resources[edge.target_id].kind,
            )
            self._relations[edge.relation_id] = edge

    def _save(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.{os.getpid()}.tmp")
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(
                self.to_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(self.path)


_ALLOWED_RELATIONS = {
    RelationKind.HOSTS: {(ResourceKind.NODE, ResourceKind.DEVICE)},
    RelationKind.CONNECTED_TO: {
        (ResourceKind.NODE, ResourceKind.TRANSPORT),
        (ResourceKind.DEVICE, ResourceKind.TRANSPORT),
    },
    RelationKind.EXPOSES: {
        (ResourceKind.NODE, ResourceKind.CAPABILITY),
        (ResourceKind.DEVICE, ResourceKind.CAPABILITY),
    },
    RelationKind.REQUIRES: {
        (ResourceKind.OPERATION, ResourceKind.CAPABILITY),
        (ResourceKind.CAPABILITY, ResourceKind.TRANSPORT),
    },
    RelationKind.OBSERVED_BY: {
        (ResourceKind.DEVICE, ResourceKind.OBSERVATION),
        (ResourceKind.OPERATION, ResourceKind.OBSERVATION),
    },
}


def _validate_relation(
    source: ResourceKind, relation: RelationKind, target: ResourceKind
) -> None:
    if (source, target) not in _ALLOWED_RELATIONS[relation]:
        raise ValueError(
            f"invalid {relation.value} relation: {source.value} -> {target.value}"
        )


__all__ = ["ResourceGraph"]

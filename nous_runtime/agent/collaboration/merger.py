"""Deterministic result merge policies for model collaboration."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from enum import Enum
from typing import Any

from nous_runtime.agent.collaboration.models import (
    AgentContribution,
    ContributionStatus,
    MergeConflict,
    MergeResult,
)
from nous_runtime.agent.errors import AgentCollaborationError


class MergePolicy(str, Enum):
    FIRST_SUCCESS = "first_success"
    CONSENSUS = "consensus"
    STRUCTURED = "structured"
    COLLECT = "collect"


class CollaborationResultMerger:
    def merge(
        self,
        contributions: tuple[AgentContribution, ...],
        *,
        policy: MergePolicy = MergePolicy.STRUCTURED,
    ) -> MergeResult:
        successful = tuple(
            item
            for item in contributions
            if item.status is ContributionStatus.COMPLETED
        )
        if not successful:
            raise AgentCollaborationError(
                "cannot merge collaboration without successful contributions"
            )
        if policy is MergePolicy.FIRST_SUCCESS:
            first = successful[0]
            return MergeResult(
                output=first.output,
                sources=(first.agent_id,),
                strategy=policy.value,
            )
        if policy is MergePolicy.COLLECT:
            return MergeResult(
                output=tuple(item.output for item in successful),
                sources=tuple(item.agent_id for item in successful),
                strategy=policy.value,
            )
        if policy is MergePolicy.CONSENSUS:
            return self._consensus(successful)
        return self._structured(successful)

    @staticmethod
    def _consensus(
        contributions: tuple[AgentContribution, ...],
    ) -> MergeResult:
        canonical = [repr(item.output) for item in contributions]
        counts = Counter(canonical)
        winner_key = sorted(
            counts,
            key=lambda item: (-counts[item], canonical.index(item), item),
        )[0]
        winner_index = canonical.index(winner_key)
        winner = contributions[winner_index]
        return MergeResult(
            output=winner.output,
            sources=tuple(
                item.agent_id
                for item, value in zip(contributions, canonical, strict=True)
                if value == winner_key
            ),
            strategy=MergePolicy.CONSENSUS.value,
        )

    @staticmethod
    def _structured(
        contributions: tuple[AgentContribution, ...],
    ) -> MergeResult:
        if not all(isinstance(item.output, Mapping) for item in contributions):
            return CollaborationResultMerger().merge(
                contributions,
                policy=MergePolicy.COLLECT,
            )
        merged: dict[str, Any] = {}
        owners: dict[str, str] = {}
        conflicts: list[MergeConflict] = []
        for item in contributions:
            for raw_key, value in item.output.items():
                key = str(raw_key)
                if key not in merged:
                    merged[key] = value
                    owners[key] = item.agent_id
                    continue
                if merged[key] != value:
                    conflicts.append(
                        MergeConflict(
                            key=key,
                            agent_ids=(owners[key], item.agent_id),
                            values=(merged[key], value),
                        )
                    )
        return MergeResult(
            output=merged,
            conflicts=tuple(conflicts),
            sources=tuple(item.agent_id for item in contributions),
            strategy=MergePolicy.STRUCTURED.value,
        )


__all__ = ["CollaborationResultMerger", "MergePolicy"]

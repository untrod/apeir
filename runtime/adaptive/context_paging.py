"""
Adaptive Context Paging — learning-based page retention and prefetch strategy.

RC8 Context VM provides the mechanism (page_types, pager, vm).
RC10 adds the learning strategy: which pages to keep, evict, prefetch.

When adaptive_context_paging is DISABLED: LRU with fixed tiering.
When adaptive_context_paging is ENABLED: page value estimation with
  predictive prefetch and adaptive eviction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from runtime.adaptive.flags import AdaptiveFlags
from runtime.adaptive.observation import DecisionRecord, DecisionType, ObservationLedger


class PageAction(str, Enum):
    KEEP = "keep"
    PREFETCH = "prefetch"
    COMPRESS = "compress"
    SUMMARIZE = "summarize"
    OFFLOAD = "offload"
    EVICT = "evict"
    RECOMPUTE = "recompute"
    PIN = "pin"


@dataclass
class PageValue:
    """Estimated value of a context page."""

    page_id: str
    reuse_probability: float
    load_cost_ms: float
    recompute_cost_ms: float
    quality_loss_if_evicted: float = 0.0
    privacy_risk: float = 0.0
    memory_pressure: float = 0.0
    critical_path_impact: float = 0.0
    last_accessed_ms: float = 0.0
    access_count: int = 0
    size_bytes: int = 0


@dataclass
class PageDecision:
    """Decision for a single page."""

    page_id: str
    action: PageAction
    reason: str
    estimated_benefit: float


class AdaptiveContextPager:
    """Learning-based context page manager.

    When disabled: LRU with fixed 3-tier strategy.
    When enabled: value-based retention with predictive prefetch.
    """

    def __init__(
        self,
        ledger: ObservationLedger | None = None,
        max_ram_pages: int = 128,
        max_nvme_pages: int = 1024,
        prefetch_threshold: float = 0.7,
    ) -> None:
        self._ledger = ledger or ObservationLedger()
        self._max_ram_pages = max_ram_pages
        self._max_nvme_pages = max_nvme_pages
        self._prefetch_threshold = prefetch_threshold
        self._access_history: dict[str, list[float]] = {}

    def decide_page_actions(
        self,
        pages: list[PageValue],
        workload_id: str = "",
        features: dict[str, Any] | None = None,
    ) -> list[PageDecision]:
        """Decide actions for all pages.

        Returns one decision per page.
        """
        flags = AdaptiveFlags.global_flags()

        decision = DecisionRecord(
            workload_id=workload_id,
            policy_id="context-pager",
            policy_revision=1,
            decision_type=DecisionType.CONTEXT_PAGING,
            feature_snapshot=features or {},
        )

        if flags.is_enabled("adaptive_context_paging"):
            decisions = self._adaptive_decide(pages)
        else:
            decisions = self._lru_decide(pages)

        self._ledger.record_decision(decision)
        return decisions

    def _lru_decide(self, pages: list[PageValue]) -> list[PageDecision]:
        """Fixed LRU with 3-tier strategy (RC9-compatible).

        RAM: most recently accessed
        NVMe: next tier
        Evict: least recently accessed (recompute if needed)
        """
        sorted_pages = sorted(pages, key=lambda p: p.last_accessed_ms, reverse=True)
        decisions = []

        for i, page in enumerate(sorted_pages):
            if i < self._max_ram_pages:
                decisions.append(
                    PageDecision(
                        page_id=page.page_id,
                        action=PageAction.KEEP,
                        reason="LRU: within RAM budget",
                        estimated_benefit=1.0,
                    )
                )
            elif i < self._max_ram_pages + self._max_nvme_pages:
                decisions.append(
                    PageDecision(
                        page_id=page.page_id,
                        action=PageAction.OFFLOAD,
                        reason="LRU: offload to NVMe",
                        estimated_benefit=0.5,
                    )
                )
            else:
                decisions.append(
                    PageDecision(
                        page_id=page.page_id,
                        action=PageAction.EVICT,
                        reason="LRU: exceed storage budget",
                        estimated_benefit=0.0,
                    )
                )

        return decisions

    def _adaptive_decide(self, pages: list[PageValue]) -> list[PageDecision]:
        """Value-based adaptive paging.

        Estimates page value from multiple dimensions:
        - Reuse probability
        - Recomputation cost
        - Quality impact
        - Memory pressure
        - Critical path impact

        Reference: SYMPHONY (NSDI'26) — hint-based prefetch with
        compute-memory disaggregation patterns.
        """
        decisions = []

        for page in pages:
            # Compute page value
            value = (
                0.30 * page.reuse_probability
                + 0.20 * (1.0 / max(1.0, page.recompute_cost_ms / 1000.0))
                + 0.20 * (1.0 - page.quality_loss_if_evicted)
                + 0.15 * page.critical_path_impact
                + 0.10 * (1.0 - page.privacy_risk)
                + 0.05 * (1.0 - page.memory_pressure)
            )

            if page.reuse_probability >= self._prefetch_threshold:
                action = PageAction.PREFETCH
                reason = f"High reuse probability: {page.reuse_probability:.2f}"
            elif value >= 0.5:
                action = PageAction.KEEP
                reason = f"High page value: {value:.2f}"
            elif value >= 0.3:
                action = PageAction.COMPRESS
                reason = f"Medium value, compress: {value:.2f}"
            elif value >= 0.15:
                if page.recompute_cost_ms < page.load_cost_ms:
                    action = PageAction.RECOMPUTE
                    reason = f"Cheaper to recompute (recompute={page.recompute_cost_ms}ms < load={page.load_cost_ms}ms)"
                else:
                    action = PageAction.OFFLOAD
                    reason = f"Low value, offload: {value:.2f}"
            else:
                action = PageAction.EVICT
                reason = f"Very low value: {value:.2f}"

            decisions.append(
                PageDecision(
                    page_id=page.page_id,
                    action=action,
                    reason=reason,
                    estimated_benefit=value,
                )
            )

        # Sort: PREFETCH and KEEP first
        action_order = {
            PageAction.PREFETCH: 0,
            PageAction.PIN: 0,
            PageAction.KEEP: 1,
            PageAction.COMPRESS: 2,
            PageAction.SUMMARIZE: 2,
            PageAction.OFFLOAD: 3,
            PageAction.RECOMPUTE: 3,
            PageAction.EVICT: 4,
        }
        decisions.sort(key=lambda d: action_order.get(d.action, 5))

        return decisions

    def record_access(self, page_id: str, timestamp_ms: float) -> None:
        """Record a page access for reuse probability estimation."""
        if page_id not in self._access_history:
            self._access_history[page_id] = []
        self._access_history[page_id].append(timestamp_ms)
        # Keep last 100 accesses
        if len(self._access_history[page_id]) > 100:
            self._access_history[page_id] = self._access_history[page_id][-100:]

    def estimate_reuse_probability(
        self, page_id: str, current_time_ms: float, window_ms: float = 60000.0
    ) -> float:
        """Estimate the probability of page reuse based on access history."""
        history = self._access_history.get(page_id, [])
        if not history:
            return 0.0

        recent = [t for t in history if current_time_ms - t <= window_ms]
        if not recent:
            return 0.0

        # Simple estimator: fraction of windows with access
        return len(recent) / max(1, len(history))

    def get_ledger(self) -> ObservationLedger:
        return self._ledger

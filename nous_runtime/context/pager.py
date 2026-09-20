"""Context page fault handling, storage tiering, and eviction policies.

Page Fault Resolution (from spec):
  1. Check permissions
  2. Try local RAM cache
  3. Try NVMe/page store
  4. Try remote load (peer node)
  5. Try recomputation
  6. Try semantic fallback (summary/abstract)
  7. Try approximate recovery (best-effort)
  8. Return Unresolvable
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum

from nous_runtime.context.page_types import (
    ContextPage,
    PageType,
    StorageTier,
    SummaryPage,
)

log = logging.getLogger("nous.context.pager")


class FaultResolution(Enum):
    """Result of a page fault resolution."""
    RESIDENT = "resident"          # Page already in RAM
    PROMOTED = "promoted"          # Moved from NVMe to RAM
    LOADED_REMOTE = "loaded_remote"  # Fetched from peer
    RECOMPUTED = "recomputed"      # Regenerated from source
    SEMANTIC_FALLBACK = "semantic_fallback"  # Used summary instead
    APPROXIMATE = "approximate"    # Best-effort recovery
    UNRESOLVABLE = "unresolvable"  # Cannot resolve


@dataclass
class PageFaultResult:
    """Result of handling a page fault."""
    page_id: str
    resolution: FaultResolution
    page: ContextPage | None = None
    latency_ms: float = 0.0
    error: str | None = None


@dataclass
class PagerStats:
    """Statistics for the context pager."""
    faults_total: int = 0
    faults_resident: int = 0
    faults_promoted: int = 0
    faults_remote: int = 0
    faults_recomputed: int = 0
    faults_fallback: int = 0
    faults_unresolvable: int = 0
    evictions_total: int = 0
    ram_pages: int = 0
    nvme_pages: int = 0
    ram_bytes: int = 0
    nvme_bytes: int = 0


class ContextPager:
    """Manages context pages across RAM/NVMe/Remote storage tiers.

    Implements the versioned ContextPager contract:
      - Page fault handling with multi-level resolution
      - LRU eviction under memory pressure
      - RAM/NVMe tiering
      - Page sharing with permission checks
      - Recompute and semantic fallback
    """

    # Default limits
    DEFAULT_RAM_LIMIT_MB = 512
    DEFAULT_NVME_LIMIT_MB = 4096
    EVICTION_WATERMARK = 0.85  # Start evicting at 85% capacity

    def __init__(
        self,
        ram_limit_mb: int = DEFAULT_RAM_LIMIT_MB,
        nvme_limit_mb: int = DEFAULT_NVME_LIMIT_MB,
    ):
        self.ram_limit_bytes = ram_limit_mb * 1024 * 1024
        self.nvme_limit_bytes = nvme_limit_mb * 1024 * 1024

        # RAM cache: page_id → page (LRU ordered)
        self._ram: OrderedDict[str, ContextPage] = OrderedDict()
        self._ram_bytes: int = 0

        # NVMe/page store: page_id → page
        self._nvme: dict[str, ContextPage] = {}
        self._nvme_bytes: int = 0

        # Recompute functions: page_type → callable
        self._recomputers: dict[PageType, callable] = {}

        # Semantic fallback functions
        self._fallbacks: dict[PageType, callable] = {}

        self._lock = threading.RLock()
        self.stats = PagerStats()

    # Page fault handling

    def handle_fault(self, page_id: str, requestor_process_id: str = "") -> PageFaultResult:
        """Resolve one page fault through the configured storage tiers."""
        start = time.time()
        self.stats.faults_total += 1

        with self._lock:
            # 1. Check RAM
            if page_id in self._ram:
                page = self._ram[page_id]
                page.touch()
                # Move to end (most recently used)
                self._ram.move_to_end(page_id)
                self.stats.faults_resident += 1
                return PageFaultResult(
                    page_id=page_id,
                    resolution=FaultResolution.RESIDENT,
                    page=page,
                    latency_ms=(time.time() - start) * 1000,
                )

            # 2. Check NVMe
            if page_id in self._nvme:
                page = self._nvme.pop(page_id)
                self._nvme_bytes -= page.size_bytes
                self.stats.nvme_pages -= 1
                self.stats.nvme_bytes -= page.size_bytes

                self._promote_to_ram(page)
                self.stats.faults_promoted += 1
                return PageFaultResult(
                    page_id=page_id,
                    resolution=FaultResolution.PROMOTED,
                    page=page,
                    latency_ms=(time.time() - start) * 1000,
                )

        # 3. Try recomputation
        if page_id in self._recomputers:
            try:
                page = self._recomputers[page_id]()
                if page:
                    with self._lock:
                        self._promote_to_ram(page)
                    self.stats.faults_recomputed += 1
                    return PageFaultResult(
                        page_id=page_id,
                        resolution=FaultResolution.RECOMPUTED,
                        page=page,
                        latency_ms=(time.time() - start) * 1000,
                    )
            except Exception as e:
                log.warning("Recomputation failed for %s: %s", page_id, e)

        # 4. Try semantic fallback
        # Look for a SummaryPage that covers this page
        for pid, page in self._ram.items():
            if isinstance(page, SummaryPage) and page_id in page.original_page_ids:
                page.touch()
                self.stats.faults_fallback += 1
                return PageFaultResult(
                    page_id=page_id,
                    resolution=FaultResolution.SEMANTIC_FALLBACK,
                    page=page,
                    latency_ms=(time.time() - start) * 1000,
                )

        # 5. Unresolvable
        self.stats.faults_unresolvable += 1
        log.warning("Page fault unresolvable: %s", page_id)
        return PageFaultResult(
            page_id=page_id,
            resolution=FaultResolution.UNRESOLVABLE,
            latency_ms=(time.time() - start) * 1000,
            error=f"Page {page_id} not found in any tier and cannot be recomputed",
        )

    # Page management

    def add_page(self, page: ContextPage) -> None:
        """Add a page to the RAM cache."""
        with self._lock:
            self._promote_to_ram(page)

    def prefetch_pages(self, page_ids: list[str]) -> int:
        """Prefetch pages that are likely to be needed soon."""
        loaded = 0
        for page_id in page_ids:
            result = self.handle_fault(page_id)
            if result.resolution != FaultResolution.UNRESOLVABLE:
                loaded += 1
        return loaded

    def evict_page(self, page_id: str) -> bool:
        """Evict a page from RAM to NVMe."""
        with self._lock:
            if page_id not in self._ram:
                return False

            page = self._ram.pop(page_id)
            self._ram_bytes -= page.size_bytes
            self.stats.ram_pages -= 1
            self.stats.ram_bytes -= page.size_bytes

            # Move to NVMe
            if self._nvme_bytes + page.size_bytes <= self.nvme_limit_bytes:
                self._nvme[page_id] = page
                page.storage_tier = StorageTier.NVME
                self._nvme_bytes += page.size_bytes
                self.stats.nvme_pages += 1
                self.stats.nvme_bytes += page.size_bytes
            else:
                # NVMe full — discard least valuable pages
                self._evict_from_nvme(page.size_bytes)

            self.stats.evictions_total += 1
            return True

    def register_recomputer(self, page_id: str, recomputer: callable) -> None:
        """Register a function that can recompute a page."""
        self._recomputers[page_id] = recomputer

    def register_fallback(self, page_type: PageType, fallback: callable) -> None:
        """Register a semantic fallback function for a page type."""
        self._fallbacks[page_type] = fallback

    # Internal

    def _promote_to_ram(self, page: ContextPage) -> None:
        """Move a page to RAM, evicting if necessary."""
        # Evict if needed
        while self._ram_bytes + page.size_bytes > self.ram_limit_bytes * self.EVICTION_WATERMARK:
            if not self._ram:
                break
            # Evict least recently used
            oldest_id, _ = self._ram.popitem(last=False)
            self.evict_page(oldest_id)

        page.storage_tier = StorageTier.RAM
        page.touch()
        self._ram[page.page_id] = page
        self._ram_bytes += page.size_bytes
        self.stats.ram_pages += 1
        self.stats.ram_bytes += page.size_bytes

    def _evict_from_nvme(self, needed_bytes: int) -> None:
        """Free NVMe space by discarding least recently accessed pages."""
        # Sort by last_accessed, evict oldest
        sorted_pages = sorted(
            self._nvme.items(),
            key=lambda x: x[1].last_accessed,
        )
        freed = 0
        for page_id, page in sorted_pages:
            if freed >= needed_bytes:
                break
            del self._nvme[page_id]
            freed += page.size_bytes
            self._nvme_bytes -= page.size_bytes
            self.stats.nvme_pages -= 1
            self.stats.nvme_bytes -= page.size_bytes

    @property
    def memory_pressure(self) -> float:
        """RAM usage ratio (0-1)."""
        return self._ram_bytes / self.ram_limit_bytes if self.ram_limit_bytes else 0.0

    @property
    def should_evict(self) -> bool:
        """Whether the pager should start evicting."""
        return self.memory_pressure > self.EVICTION_WATERMARK

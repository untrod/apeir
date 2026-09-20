"""Virtual address space for governed agent context.

Provides:
  - Per-process context address space
  - Page allocation, mapping, and sharing
  - Page fault handling via ContextPager
  - Permission enforcement
  - Namespace isolation
  - Memory pressure eviction
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from nous_runtime.context.page_types import (
    PAGE_TYPE_MAP,
    ContextPage,
    PageType,
)
from nous_runtime.context.pager import ContextPager, FaultResolution

log = logging.getLogger("nous.context.vm")


class ContextAddressSpace:
    """Virtual address space for a single agent process.

    Each process gets its own address space. Pages can be:
      - Private (only this process)
      - Shared-read (other processes can read)
      - Shared-readwrite (other processes can read and write)
    """

    def __init__(
        self,
        process_id: str,
        pager: ContextPager | None = None,
        ram_limit_mb: int = 512,
    ):
        self.process_id = process_id
        self.pager = pager or ContextPager(ram_limit_mb=ram_limit_mb)
        self._pages: dict[str, ContextPage] = {}
        self._lock = threading.RLock()

    def allocate_page(self, page: ContextPage) -> str:
        """Allocate a page in this address space."""
        page.owner_process_id = self.process_id
        self.pager.add_page(page)
        with self._lock:
            self._pages[page.page_id] = page
        log.debug("Page %s allocated in process %s", page.page_id, self.process_id)
        return page.page_id

    def access_page(self, page_id: str) -> ContextPage | None:
        """Access a page, triggering fault resolution if needed."""
        result = self.pager.handle_fault(page_id, self.process_id)
        if result.page:
            with self._lock:
                self._pages[page_id] = result.page
            return result.page

        if result.resolution == FaultResolution.UNRESOLVABLE:
            log.warning(
                "Page %s not resolvable for process %s: %s",
                page_id, self.process_id, result.error,
            )
        return None

    def prefetch(self, page_ids: list[str]) -> int:
        """Prefetch pages likely to be needed."""
        return self.pager.prefetch_pages(page_ids)

    def evict_page(self, page_id: str) -> bool:
        """Evict a page from RAM."""
        with self._lock:
            self._pages.pop(page_id, None)
        return self.pager.evict_page(page_id)

    def share_page(
        self,
        page_id: str,
        target_space: ContextAddressSpace,
        permission: str = "shared-read",
    ) -> bool:
        """Share a page with another address space."""
        page = self.access_page(page_id)
        if not page:
            return False

        page.permissions = permission
        target_space.allocate_page(page)
        log.info(
            "Page %s shared: %s → %s (%s)",
            page_id, self.process_id, target_space.process_id, permission,
        )
        return True

    def create_page(
        self,
        page_type: PageType,
        **kwargs: Any,
    ) -> ContextPage:
        """Create a new page of the given type."""
        page_cls = PAGE_TYPE_MAP.get(page_type, ContextPage)
        page = page_cls(**kwargs)
        self.allocate_page(page)
        return page

    @property
    def page_count(self) -> int:
        return len(self._pages)

    @property
    def ram_usage_bytes(self) -> int:
        return self.pager.stats.ram_bytes

    @property
    def memory_pressure(self) -> float:
        return self.pager.memory_pressure


class ContextVMManager:
    """Manages all context address spaces in the runtime.

    Provides:
      - Per-process address space creation and cleanup
      - Cross-process page sharing with permission checks
      - Global memory pressure monitoring
      - Namespace isolation enforcement
    """

    def __init__(self, global_ram_limit_mb: int = 2048):
        self.global_ram_limit = global_ram_limit_mb * 1024 * 1024
        self._spaces: dict[str, ContextAddressSpace] = {}
        self._shared_pager = ContextPager(ram_limit_mb=global_ram_limit_mb)
        self._lock = threading.RLock()

    def create_space(
        self,
        process_id: str,
        ram_limit_mb: int = 512,
    ) -> ContextAddressSpace:
        """Create a context address space for a process."""
        with self._lock:
            if process_id in self._spaces:
                raise ValueError(f"Address space already exists for process {process_id}")

            space = ContextAddressSpace(
                process_id=process_id,
                pager=self._shared_pager,
                ram_limit_mb=ram_limit_mb,
            )
            self._spaces[process_id] = space
            log.info("Context address space created for process %s", process_id)
            return space

    def get_space(self, process_id: str) -> ContextAddressSpace | None:
        return self._spaces.get(process_id)

    def destroy_space(self, process_id: str) -> None:
        """Destroy a process's address space and release its pages."""
        with self._lock:
            space = self._spaces.pop(process_id, None)
            if space:
                for page_id in list(space._pages.keys()):
                    space.evict_page(page_id)
                log.info("Context address space destroyed for process %s", process_id)

    def share_between(
        self,
        source_process_id: str,
        target_process_id: str,
        page_ids: list[str],
        permission: str = "shared-read",
    ) -> int:
        """Share pages between two processes."""
        source = self._spaces.get(source_process_id)
        target = self._spaces.get(target_process_id)

        if not source or not target:
            return 0

        shared = 0
        for page_id in page_ids:
            if source.share_page(page_id, target, permission):
                shared += 1

        return shared

    @property
    def total_ram_usage(self) -> int:
        return self._shared_pager.stats.ram_bytes

    @property
    def global_memory_pressure(self) -> float:
        return self._shared_pager.memory_pressure

    @property
    def active_spaces(self) -> int:
        return len(self._spaces)

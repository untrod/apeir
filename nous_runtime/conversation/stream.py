"""Bounded, reconnect-safe streaming message assembly."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class StreamChunk:
    event_id: str
    text: str
    final: bool = False


class ConversationStream:
    def __init__(self, *, max_visible_chars: int = 64_000, dedup_window: int = 4096):
        self.max_visible_chars = max(1, max_visible_chars)
        self._seen: set[str] = set()
        self._seen_order: deque[str] = deque(maxlen=max(1, dedup_window))
        self._parts: deque[str] = deque()
        self._size = 0
        self.complete = False

    def accept(self, chunk: StreamChunk) -> bool:
        if not chunk.event_id or chunk.event_id in self._seen:
            return False
        if len(self._seen_order) == self._seen_order.maxlen:
            self._seen.discard(self._seen_order[0])
        self._seen.add(chunk.event_id)
        self._seen_order.append(chunk.event_id)
        self._parts.append(chunk.text)
        self._size += len(chunk.text)
        while self._parts and self._size > self.max_visible_chars:
            self._size -= len(self._parts.popleft())
        self.complete = self.complete or chunk.final
        return True

    def render(self) -> str:
        return "".join(self._parts)
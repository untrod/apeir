"""Persistent terminal conversation coordination over ConversationStore."""

from __future__ import annotations

import json
import queue
import re
import threading
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from nous_runtime.conversation import ConversationMessage, ConversationStore

Executor = Callable[[str, threading.Event], str]


@dataclass(frozen=True)
class TerminalResult:
    operation_id: str
    status: str
    content: str
    conversation_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TerminalSession:
    """A terminal view/controller; ConversationStore remains authoritative."""

    def __init__(
        self,
        root: str | Path = ".",
        *,
        workspace_id: str = "local",
        owner_id: str = "local",
        conversation_id: str = "",
        active_window: int = 100,
    ) -> None:
        self.root = Path(root).resolve()
        self.workspace_id = workspace_id or "local"
        self.owner_id = owner_id or "local"
        self.store = ConversationStore(self.root, active_window=active_window)
        self.cancel_event = threading.Event()
        self.conversation_id = self._open(conversation_id)
        self.recovered_operations = self._recover_interrupted()

    def _open(self, conversation_id: str) -> str:
        if conversation_id:
            conversation = self.store.get(
                conversation_id,
                workspace_id=self.workspace_id,
                owner_id=self.owner_id,
            )
            if conversation is None:
                raise PermissionError("terminal conversation is unavailable")
            return conversation.conversation_id
        conversations = self.store.list(
            workspace_id=self.workspace_id,
            owner_id=self.owner_id,
            limit=1,
        )
        if conversations:
            return conversations[0].conversation_id
        return self.store.create(
            self.workspace_id,
            self.owner_id,
            title="Terminal conversation",
        ).conversation_id

    def execute(self, text: str, executor: Executor) -> TerminalResult:
        if not text.strip():
            raise ValueError("terminal input is required")
        operation_id = f"op_{uuid.uuid4().hex}"
        self.cancel_event.clear()
        self.store.append(ConversationMessage(self.conversation_id, "user", text))
        self._operation_event(operation_id, "started")
        results: queue.SimpleQueue[tuple[str, str]] = queue.SimpleQueue()

        def invoke() -> None:
            try:
                results.put(("completed", str(executor(text, self.cancel_event))))
            except Exception as exc:
                results.put(("failed", str(exc)))

        worker = threading.Thread(
            target=invoke,
            name=f"nous-terminal-{operation_id[-8:]}",
            daemon=True,
        )
        worker.start()
        try:
            while worker.is_alive():
                worker.join(timeout=0.05)
        except KeyboardInterrupt:
            self.cancel_event.set()
            self._operation_event(operation_id, "cancelled")
            return TerminalResult(
                operation_id, "cancelled", "", self.conversation_id
            )
        status, content = results.get()
        if self.cancel_event.is_set():
            status = "cancelled"
            content = ""
        self._operation_event(operation_id, status)
        if status != "cancelled" and content:
            self.store.append(
                ConversationMessage(
                    self.conversation_id,
                    "assistant",
                    content,
                    metadata={
                        "terminal_operation_id": operation_id,
                        "terminal_status": status,
                    },
                )
            )
        return TerminalResult(operation_id, status, content, self.conversation_id)

    def cancel_active(self) -> None:
        self.cancel_event.set()

    def history_page(self, page: int = 1, *, page_size: int = 20) -> dict[str, Any]:
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 100))
        offset = (page - 1) * page_size
        messages = self.store.history(
            self.conversation_id,
            limit=page_size + 1,
            offset=offset,
            newest_first=True,
        )
        has_more = len(messages) > page_size
        messages = messages[:page_size]
        return {
            "conversation_id": self.conversation_id,
            "page": page,
            "page_size": page_size,
            "has_more": has_more,
            "messages": [message.to_dict() for message in messages],
        }

    def search(
        self, query: str, *, page: int = 1, page_size: int = 20
    ) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("search query is required")
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 100))
        matches = self.store.search_messages(
            query,
            conversation_id=self.conversation_id,
            limit=page_size + 1,
            offset=(page - 1) * page_size,
        )
        return {
            "conversation_id": self.conversation_id,
            "query": query,
            "page": page,
            "page_size": page_size,
            "has_more": len(matches) > page_size,
            "messages": [message.to_dict() for message in matches[:page_size]],
        }

    def context_snapshot(self) -> dict[str, Any]:
        return self.store.context_window(self.conversation_id)

    def _operation_event(self, operation_id: str, state: str) -> None:
        self.store.append(
            ConversationMessage(
                self.conversation_id,
                "tool",
                json.dumps(
                    {"operation_id": operation_id, "state": state},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                event_id=f"{operation_id}:{state}",
                metadata={
                    "terminal_operation_id": operation_id,
                    "terminal_operation_state": state,
                },
            )
        )

    def _recover_interrupted(self) -> int:
        messages = self.store.history(
            self.conversation_id,
            limit=100,
            newest_first=True,
        )
        states: dict[str, str] = {}
        for message in reversed(messages):
            operation_id = str(message.metadata.get("terminal_operation_id") or "")
            state = str(message.metadata.get("terminal_operation_state") or "")
            if operation_id and state:
                states[operation_id] = state
        interrupted = [
            operation_id for operation_id, state in states.items() if state == "started"
        ]
        for operation_id in interrupted:
            self._operation_event(operation_id, "interrupted")
        return len(interrupted)


_FENCE = chr(96) * 3
_CODE_BLOCK = re.compile(
    rf"(^|\n){re.escape(_FENCE)}([^\n]*)\n(.*?)\n{re.escape(_FENCE)}",
    re.DOTALL,
)


def fold_output(
    text: str,
    *,
    max_code_lines: int = 24,
    max_tool_lines: int = 16,
) -> str:
    """Fold verbose code and tool traces while preserving explicit summaries."""

    def fold_code(match: re.Match[str]) -> str:
        prefix, language, body = match.groups()
        lines = body.splitlines()
        if len(lines) <= max_code_lines:
            return match.group(0)
        visible = "\n".join(lines[:max_code_lines])
        return (
            f"{prefix}{_FENCE}{language}\n{visible}\n"
            f"... [{len(lines) - max_code_lines} code lines folded]\n{_FENCE}"
        )

    folded = _CODE_BLOCK.sub(fold_code, text)
    lines = folded.splitlines()
    tool_lines = [
        index
        for index, line in enumerate(lines)
        if line.lstrip().startswith(
            ("Tool:", "Execution Trace:", "  Tool:", "  Execution")
        )
    ]
    if len(tool_lines) > max_tool_lines:
        keep = set(tool_lines[:max_tool_lines])
        hidden = len(tool_lines) - max_tool_lines
        lines = [
            line
            for index, line in enumerate(lines)
            if index not in tool_lines or index in keep
        ]
        lines.append(f"... [{hidden} tool log lines folded]")
    return "\n".join(lines)


def stream_chunks(text: str, *, chunk_chars: int = 512) -> Iterator[str]:
    """Yield Unicode-safe rendering batches with a hard upper bound."""
    chunk_chars = max(32, min(int(chunk_chars), 4096))
    for start in range(0, len(text), chunk_chars):
        yield text[start : start + chunk_chars]

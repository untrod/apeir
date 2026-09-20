# -*- coding: utf-8 -*-
"""StructuredEventParser — parses structured output from agent subprocesses."""

from __future__ import annotations

import json
import logging
from typing import Any


class StructuredEventParser:
    """Parses JSON and JSONL events from agent stdout.

    Supports two execution modes:
    1. Structured (JSON/JSONL) mode — each line is a JSON event
    2. Plain stream mode — raw text with optional event markers
    """

    def __init__(self):
        self._events: list[dict[str, Any]] = []

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    def parse_line(self, line: str) -> dict[str, Any] | None:
        """Parse a single line as a JSON event.

        Returns the parsed event dict, or None if the line is not valid JSON.
        """
        stripped = line.strip()
        if not stripped:
            return None
        try:
            event = json.loads(stripped)
            if isinstance(event, dict):
                self._events.append(event)
                return event
        except json.JSONDecodeError:
            logging.debug("Non-JSON line in agent event stream: %.100s", stripped)
        return None

    def parse_stream(self, text: str) -> list[dict[str, Any]]:
        """Parse a multi-line text stream, extracting all JSON events."""
        parsed: list[dict[str, Any]] = []
        for line in text.splitlines():
            event = self.parse_line(line)
            if event is not None:
                parsed.append(event)
        return parsed

    def extract_event_type(self, event: dict[str, Any]) -> str:
        """Extract the event type from a structured event."""
        return str(
            event.get("type")
            or event.get("event")
            or event.get("event_type")
            or "unknown"
        )

    def extract_progress(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """Extract progress information from an event, if present."""
        progress = event.get("progress")
        if isinstance(progress, dict):
            return progress
        if "step" in event or "percent" in event:
            return {
                "step": event.get("step"),
                "percent": event.get("percent"),
                "message": event.get("message"),
            }
        return None

    def extract_errors(self, event: dict[str, Any]) -> list[str]:
        """Extract error messages from an event."""
        errors: list[str] = []
        if event.get("error"):
            errors.append(str(event["error"]))
        if event.get("errors"):
            for e in event["errors"]:
                errors.append(str(e))
        return errors

    def reset(self) -> None:
        self._events = []

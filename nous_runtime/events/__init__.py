# -*- coding: utf-8 -*-
"""Canonical run state model and event stream for Nous Runtime."""

from nous_runtime.core.events import EventEnvelope
from nous_runtime.events.models import RunState, EventType, RunEvent, RunRecord, SCHEMA_VERSION
from nous_runtime.events.stream import EventStream, EventStreamError
from nous_runtime.events.event_types import (
    RuntimeEvent,
    RuntimeEventDomain,
    EVENT_CATEGORIES,
    get_event_domain,
    is_event_in_category,
)
from nous_runtime.events.bus import (
    RuntimeEventBus,
    BusMetrics,
    get_event_bus,
    reset_event_bus,
)

__all__ = [
    # Models
    "RunState",
    "EventType",
    "RunEvent",
    "RunRecord",
    "EventStream",
    "EventStreamError",
    "EventEnvelope",
    "SCHEMA_VERSION",
    # Event types
    "RuntimeEvent",
    "RuntimeEventDomain",
    "EVENT_CATEGORIES",
    "get_event_domain",
    "is_event_in_category",
    # Event bus
    "RuntimeEventBus",
    "BusMetrics",
    "get_event_bus",
    "reset_event_bus",
]

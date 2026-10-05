"""Conservative connectivity projections for Compute Mesh nodes.

The projection is deliberately controller-local.  It does not grant authority
and it never turns a persisted heartbeat into proof of a live connection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum


class NodeConnectivityState(str, Enum):
    RECONNECTING = "RECONNECTING"
    RECONCILING = "RECONCILING"
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    OFFLINE = "OFFLINE"


@dataclass(frozen=True)
class NodeConnectivityProjection:
    state: NodeConnectivityState
    lease_expires_at: str
    lease_valid: bool
    schedulable: bool
    observation_age_seconds: float | None


def project_node_connectivity(
    *,
    connected: bool,
    connection_phase: str,
    last_observed_at: str,
    heartbeat_seconds: float,
    now: datetime | None = None,
) -> NodeConnectivityProjection:
    """Project a Node state from live transport and durable signed evidence.

    A connectivity lease is only a freshness window for placement.  It is not a
    Kernel Permit, a resource Lease, or proof that a remote effect completed.
    """

    if heartbeat_seconds <= 0:
        raise ValueError("heartbeat_seconds must be positive")
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    observed = _parse_timestamp(last_observed_at)
    age = max((reference - observed).total_seconds(), 0.0) if observed else None
    lease_seconds = heartbeat_seconds * 3
    lease_valid = age is not None and age <= lease_seconds
    lease_expires_at = (
        _format_timestamp(observed + timedelta(seconds=lease_seconds))
        if observed
        else ""
    )

    if connected:
        try:
            state = NodeConnectivityState(connection_phase)
        except ValueError:
            state = NodeConnectivityState.RECONCILING
        if state not in {
            NodeConnectivityState.RECONNECTING,
            NodeConnectivityState.RECONCILING,
            NodeConnectivityState.ONLINE,
        }:
            state = NodeConnectivityState.RECONCILING
    elif age is None:
        state = NodeConnectivityState.OFFLINE
    elif lease_valid:
        state = NodeConnectivityState.DEGRADED
    elif age <= lease_seconds * 2:
        state = NodeConnectivityState.STALE
    else:
        state = NodeConnectivityState.OFFLINE

    return NodeConnectivityProjection(
        state=state,
        lease_expires_at=lease_expires_at,
        lease_valid=lease_valid,
        schedulable=(
            state is NodeConnectivityState.ONLINE
            or (state is NodeConnectivityState.DEGRADED and lease_valid)
        ),
        observation_age_seconds=age,
    )


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )

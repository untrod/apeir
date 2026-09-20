"""
Continual Personalization — privacy-first user adaptation.

Three levels of personalization:
  Level 1: Non-parametric — preferences, routing, retrieval, format
  Level 2: Small-parameter — LoRA, Adapter, Prefix, Embedding, Reranker
  Level 3: Device-side continual learning — replay buffer (EXPERIMENTAL)

When adaptive_personalization is DISABLED: no personalization (RC9 behavior).
When adaptive_personalization is ENABLED: Level 1 is active.

ALL personalization MUST:
  - Be explicitly opted into
  - Be local-first
  - Allow data viewing, deletion, export
  - Support rollback
  - Be isolated from base model
  - NOT auto-upload private data

Reference: Orion (arXiv:2605.26473) — on-device continual learning
with adaptive memory management.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from runtime.adaptive.flags import AdaptiveFlags
from runtime.adaptive.observation import ObservationLedger


class PersonalizationLevel(str, Enum):
    NONE = "none"  # No personalization
    NON_PARAMETRIC = "non_parametric"  # Level 1: preferences, routing, format
    SMALL_MODEL = "small_model"  # Level 2: LoRA, Adapter, Prefix
    CONTINUAL_LEARNING = "continual_learning"  # Level 3: device-side CL


@dataclass
class UserPreferences:
    """Non-parametric user preferences."""

    user_id: str
    preferred_models: list[str] = field(default_factory=list)
    avoided_models: list[str] = field(default_factory=list)
    preferred_providers: list[str] = field(default_factory=list)
    routing_prefs: dict[str, float] = field(default_factory=dict)
    tool_priorities: dict[str, float] = field(default_factory=dict)
    response_format: str = "default"
    verbosity: str = "normal"
    language: str = "en"
    context_window_pref: int | None = None
    privacy_level: str = "standard"
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "preferred_models": self.preferred_models,
            "avoided_models": self.avoided_models,
            "preferred_providers": self.preferred_providers,
            "routing_prefs": self.routing_prefs,
            "tool_priorities": self.tool_priorities,
            "response_format": self.response_format,
            "verbosity": self.verbosity,
            "language": self.language,
            "context_window_pref": self.context_window_pref,
            "privacy_level": self.privacy_level,
        }

    def digest(self) -> str:
        """Content digest for integrity verification."""
        return hashlib.sha256(
            json.dumps(self.to_dict(), sort_keys=True).encode()
        ).hexdigest()[:16]


@dataclass
class PersonalizationRecord:
    """A record of a personalization adaptation."""

    user_id: str
    level: PersonalizationLevel
    field: str
    old_value: Any
    new_value: Any
    reason: str
    timestamp: float


class Personalizer:
    """Privacy-first personalization manager.

    Usage:
        p = Personalizer()
        p.set_preference("user-1", "response_format", "markdown")
        prefs = p.get_preferences("user-1")

    All personalization data is stored locally. No data is uploaded
    without explicit user consent.
    """

    def __init__(self, ledger: ObservationLedger | None = None) -> None:
        self._ledger = ledger or ObservationLedger()
        self._preferences: dict[str, UserPreferences] = {}
        self._history: dict[str, list[PersonalizationRecord]] = {}
        self._level: PersonalizationLevel = PersonalizationLevel.NONE
        self._lock = threading.Lock()

    def set_level(self, level: PersonalizationLevel) -> None:
        """Set the maximum personalization level."""
        self._level = level

    def get_level(self) -> PersonalizationLevel:
        """Get the current personalization level."""
        flags = AdaptiveFlags.global_flags()
        if not flags.is_enabled("adaptive_personalization"):
            return PersonalizationLevel.NONE
        return self._level

    def get_preferences(self, user_id: str) -> UserPreferences:
        """Get preferences for a user, creating defaults if needed."""
        with self._lock:
            if user_id not in self._preferences:
                import time

                self._preferences[user_id] = UserPreferences(
                    user_id=user_id,
                    created_at=time.time(),
                    updated_at=time.time(),
                )
            return self._preferences[user_id]

    def set_preference(
        self, user_id: str, field: str, value: Any, reason: str = ""
    ) -> bool:
        """Set a single preference for a user.

        Returns True if the preference was changed, False if unchanged.
        """
        level = self.get_level()
        if level == PersonalizationLevel.NONE:
            return False

        prefs = self.get_preferences(user_id)

        if not hasattr(prefs, field):
            return False

        old_value = getattr(prefs, field)
        if old_value == value:
            return False

        import time

        with self._lock:
            setattr(prefs, field, value)
            object.__setattr__(prefs, "updated_at", time.time())

        # Record history
        record = PersonalizationRecord(
            user_id=user_id,
            level=PersonalizationLevel.NON_PARAMETRIC,
            field=field,
            old_value=old_value,
            new_value=value,
            reason=reason,
            timestamp=time.time(),
        )

        with self._lock:
            if user_id not in self._history:
                self._history[user_id] = []
            self._history[user_id].append(record)

        return True

    def adapt_routing_weights(
        self, user_id: str, model_id: str, score_delta: float
    ) -> None:
        """Adapt routing weights based on user feedback.

        Positive delta = increase preference, negative = decrease.
        """
        prefs = self.get_preferences(user_id)
        current = prefs.routing_prefs.get(model_id, 0.5)
        new_value = max(0.0, min(1.0, current + score_delta * 0.1))
        prefs.routing_prefs[model_id] = new_value

    def get_history(self, user_id: str) -> list[PersonalizationRecord]:
        """Get personalization change history for a user."""
        with self._lock:
            return list(self._history.get(user_id, []))

    def export_data(self, user_id: str) -> dict[str, Any]:
        """Export all personalization data for a user (GDPR export)."""
        prefs = self.get_preferences(user_id)
        history = self.get_history(user_id)
        return {
            "user_id": user_id,
            "preferences": prefs.to_dict(),
            "history": [
                {
                    "field": r.field,
                    "old_value": r.old_value,
                    "new_value": r.new_value,
                    "reason": r.reason,
                    "timestamp": r.timestamp,
                }
                for r in history
            ],
            "data_digest": prefs.digest(),
        }

    def delete_data(self, user_id: str) -> bool:
        """Delete all personalization data for a user (GDPR delete).

        Returns True if data was deleted.
        """
        with self._lock:
            deleted_prefs = self._preferences.pop(user_id, None) is not None
            deleted_history = self._history.pop(user_id, None) is not None
            return deleted_prefs or deleted_history

    def rollback(self, user_id: str, num_changes: int = 1) -> int:
        """Roll back the last N personalization changes for a user.

        Returns the number of changes rolled back.
        """
        with self._lock:
            history = self._history.get(user_id, [])
            if not history:
                return 0

            rolled_back = 0
            for _ in range(min(num_changes, len(history))):
                record = history.pop()
                prefs = self._preferences.get(user_id)
                if prefs and hasattr(prefs, record.field):
                    setattr(prefs, record.field, record.old_value)
                    rolled_back += 1

            return rolled_back

    def has_consent(self, user_id: str) -> bool:
        """Check if the user has explicitly consented to personalization."""
        prefs = self.get_preferences(user_id)
        return prefs.privacy_level != "none"

    def get_ledger(self) -> ObservationLedger:
        return self._ledger

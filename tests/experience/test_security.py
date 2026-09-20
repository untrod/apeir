# -*- coding: utf-8 -*-
"""Tests for Experience Security — 20 tests."""

from __future__ import annotations

import pytest
from nous_runtime.experience.models import ExperienceRecord
from nous_runtime.experience.schema import ExperienceStatus
from nous_runtime.experience.security import (
    ExperienceAccessDecision,
    ExperienceAccessRequest,
    ExperienceGuard,
)


@pytest.fixture
def guard():
    return ExperienceGuard()


class TestExperienceAccess:
    def test_request_create(self):
        req = ExperienceAccessRequest(actor="agent_01", actor_type="agent", action="read")
        assert req.actor == "agent_01"

    def test_decision_create(self):
        dec = ExperienceAccessDecision(allowed=True, reason="ok")
        assert dec.allowed is True


class TestExperienceGuard:
    def test_system_can_read(self, guard):
        dec = guard.authorize(ExperienceAccessRequest(actor="sys", actor_type="system", action="read"))
        assert dec.allowed is True

    def test_system_can_write(self, guard):
        dec = guard.authorize(ExperienceAccessRequest(actor="sys", actor_type="system", action="write"))
        assert dec.allowed is True

    def test_system_can_modify(self, guard):
        dec = guard.authorize(ExperienceAccessRequest(actor="sys", actor_type="system", action="modify"))
        assert dec.allowed is True

    def test_agent_can_read(self, guard):
        dec = guard.authorize(ExperienceAccessRequest(actor="agent_01", actor_type="agent", action="read"))
        assert dec.allowed is True

    def test_agent_cannot_write(self, guard):
        dec = guard.authorize(ExperienceAccessRequest(actor="agent_01", actor_type="agent", action="write"))
        assert dec.allowed is False

    def test_agent_cannot_modify(self, guard):
        dec = guard.authorize(ExperienceAccessRequest(actor="agent_01", actor_type="agent", action="modify"))
        assert dec.allowed is False

    def test_agent_cannot_delete(self, guard):
        dec = guard.authorize(ExperienceAccessRequest(actor="agent_01", actor_type="agent", action="delete"))
        assert dec.allowed is False

    def test_user_can_read(self, guard):
        dec = guard.authorize(ExperienceAccessRequest(actor="user_1", actor_type="user", action="read"))
        assert dec.allowed is True

    def test_user_can_write(self, guard):
        dec = guard.authorize(ExperienceAccessRequest(actor="user_1", actor_type="user", action="write"))
        assert dec.allowed is True

    def test_unknown_type_denied(self, guard):
        dec = guard.authorize(ExperienceAccessRequest(actor="bot", actor_type="bot", action="read"))
        assert dec.allowed is False

    def test_validate_experience_valid(self, guard):
        r = ExperienceRecord(task_type="coding", action="refactor", source_type="agent", success=True)
        violations = guard.validate_experience(r)
        assert violations == []

    def test_validate_missing_task_type(self, guard):
        r = ExperienceRecord(action="refactor", source_type="agent")
        violations = guard.validate_experience(r)
        assert any("task_type" in v for v in violations)

    def test_validate_failure_needs_reason(self, guard):
        r = ExperienceRecord(task_type="coding", action="test", success=False, source_type="agent")
        violations = guard.validate_experience(r)
        assert any("failure_reason" in v for v in violations)

    def test_validate_trusted_needs_occurrences(self, guard):
        r = ExperienceRecord(task_type="coding", action="test", source_type="agent",
                            status=ExperienceStatus.TRUSTED.value, occurrence_count=1)
        violations = guard.validate_experience(r)
        assert any("TRUSTED" in v for v in violations)

    def test_filter_injection_removes_control_chars(self, guard):
        text = "normal text\x00\x01\x02with nulls"
        cleaned = guard.filter_injection(text)
        assert "\x00" not in cleaned

    def test_filter_injection_length_limit(self, guard):
        long_text = "x" * 5000
        cleaned = guard.filter_injection(long_text)
        assert len(cleaned) <= 2000

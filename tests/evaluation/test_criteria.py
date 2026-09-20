# -*- coding: utf-8 -*-
"""Tests for Evaluation Criteria — 20 tests."""

from __future__ import annotations

from nous_runtime.evaluation.criteria import (
    Criterion,
    CriteriaRegistry,
    STANDARD_CRITERIA,
)
from nous_runtime.evaluation.schema import EvaluationDimension


class TestCriterion:
    def test_create(self):
        c = Criterion(key="test", dimension="correctness", label="Test", description="Test criterion")
        assert c.key == "test"
        assert c.weight_in_dimension == 1.0

    def test_thresholds(self):
        c = Criterion(key="t", dimension="correctness", label="T", threshold_pass=0.9, threshold_warn=0.5)
        assert c.threshold_pass == 0.9
        assert c.threshold_warn == 0.5

    def test_to_dict(self):
        c = Criterion(key="pytest", dimension="correctness", label="Tests", description="Run tests")
        d = c.to_dict()
        assert d["key"] == "pytest"
        assert d["label"] == "Tests"


class TestCriteriaRegistry:
    def test_create_default(self):
        reg = CriteriaRegistry()
        assert len(reg.list_all()) > 0

    def test_get_known_criterion(self):
        reg = CriteriaRegistry()
        c = reg.get("pytest")
        assert c is not None
        assert c.dimension == EvaluationDimension.CORRECTNESS.value

    def test_get_unknown(self):
        reg = CriteriaRegistry()
        assert reg.get("nonexistent") is None

    def test_get_criteria_for_dimension(self):
        reg = CriteriaRegistry()
        criteria = reg.get_criteria_for("correctness")
        assert len(criteria) >= 3  # pytest, compile, type_check, schema_check

    def test_get_criteria_for_security(self):
        reg = CriteriaRegistry()
        criteria = reg.get_criteria_for("security")
        assert len(criteria) >= 2

    def test_get_dimensions(self):
        reg = CriteriaRegistry()
        dims = reg.get_dimensions()
        assert "correctness" in dims
        assert "security" in dims

    def test_dimension_weights(self):
        reg = CriteriaRegistry()
        weights = reg.dimension_weights()
        assert abs(sum(weights.values()) - 1.0) < 0.01
        assert weights["correctness"] == 0.30

    def test_standard_criteria_coverage(self):
        """All 5 dimensions have at least one criterion."""
        reg = CriteriaRegistry()
        for dim in ("correctness", "reliability", "security", "performance", "maintainability"):
            assert len(reg.get_criteria_for(dim)) >= 1, f"No criteria for {dim}"

    def test_custom_criteria(self):
        custom = {
            "custom_test": Criterion(key="custom_test", dimension="correctness", label="Custom"),
        }
        reg = CriteriaRegistry(criteria=custom)
        assert reg.get("custom_test") is not None

    def test_to_dict(self):
        reg = CriteriaRegistry()
        d = reg.to_dict()
        assert "criteria" in d
        assert "dimension_weights" in d

    def test_pytest_criterion_weight(self):
        reg = CriteriaRegistry()
        c = reg.get("pytest")
        assert c.weight_in_dimension == 0.40

    def test_ruff_criterion_dimension(self):
        reg = CriteriaRegistry()
        c = reg.get("ruff")
        assert c.dimension == EvaluationDimension.MAINTAINABILITY.value

    def test_security_scan_threshold(self):
        reg = CriteriaRegistry()
        c = reg.get("security_scan")
        assert c.threshold_pass == 0.95

    def test_benchmark_criterion(self):
        reg = CriteriaRegistry()
        c = reg.get("benchmark")
        assert c.dimension == EvaluationDimension.PERFORMANCE.value

    def test_all_criteria_have_required_fields(self):
        for key, c in STANDARD_CRITERIA.items():
            assert c.key == key
            assert c.dimension != ""
            assert c.label != ""
            assert c.weight_in_dimension > 0

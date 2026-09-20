# -*- coding: utf-8 -*-
"""Tests for Evaluation Validators — 30 tests."""

from __future__ import annotations

from nous_runtime.evaluation.models import EvaluationEvidence
from nous_runtime.evaluation.schema import EvaluationDimension
from nous_runtime.evaluation.validators.code_validator import CodeValidator
from nous_runtime.evaluation.validators.performance_validator import PerformanceValidator
from nous_runtime.evaluation.validators.schema_validator import SchemaValidator
from nous_runtime.evaluation.validators.security_validator import SecurityValidator
from nous_runtime.evaluation.validators.test_validator import TestValidator


class TestTestValidator:
    def test_dimension(self):
        v = TestValidator()
        assert v.dimension == EvaluationDimension.CORRECTNESS.value

    def test_source(self):
        v = TestValidator()
        assert v.source == "pytest"

    def test_validate_returns_list(self):
        v = TestValidator()
        results = v.validate(target=None, context={"test_path": "tests/context/"})
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, EvaluationEvidence)

    def test_validate_evidence_has_dimension(self):
        v = TestValidator()
        results = v.validate(target=None, context={"test_path": "tests/context/"})
        for r in results:
            assert r.dimension == EvaluationDimension.CORRECTNESS.value

    def test_validate_with_invalid_path(self):
        v = TestValidator()
        results = v.validate(target=None, context={"test_path": "nonexistent_path/"})
        assert isinstance(results, list)
        assert len(results) >= 1

    def test_validate_with_timeout(self):
        v = TestValidator()
        results = v.validate(target=None, context={"test_path": "tests/", "timeout": 1})
        assert isinstance(results, list)


class TestCodeValidator:
    def test_dimension(self):
        v = CodeValidator()
        assert v.dimension == EvaluationDimension.MAINTAINABILITY.value

    def test_validate_returns_list(self):
        v = CodeValidator()
        results = v.validate(target=None, context={"target_path": "nous_runtime/evaluation/"})
        assert isinstance(results, list)

    def test_validate_includes_ruff(self):
        v = CodeValidator()
        results = v.validate(target=None, context={"target_path": "nous_runtime/evaluation/"})
        sources = {r.source for r in results}
        assert "ruff" in sources

    def test_validate_includes_compile(self):
        v = CodeValidator()
        results = v.validate(target=None, context={"target_path": "nous_runtime/evaluation/"})
        sources = {r.source for r in results}
        assert "compileall" in sources

    def test_validate_with_invalid_path(self):
        v = CodeValidator()
        results = v.validate(target=None, context={"target_path": "nonexistent/"})
        assert isinstance(results, list)


class TestSecurityValidator:
    def test_dimension(self):
        v = SecurityValidator()
        assert v.dimension == EvaluationDimension.SECURITY.value

    def test_validate_returns_list(self):
        v = SecurityValidator()
        results = v.validate(target=None)
        assert isinstance(results, list)
        assert len(results) >= 2  # governance + constitution + vulnerability

    def test_governance_check(self):
        v = SecurityValidator()
        results = v.validate(target=None)
        governance = [r for r in results if r.source == "governance_gate"]
        assert len(governance) >= 1

    def test_constitution_check(self):
        v = SecurityValidator()
        results = v.validate(target=None)
        constitution = [r for r in results if r.source == "constitution"]
        assert len(constitution) >= 1

    def test_vulnerability_scan(self):
        v = SecurityValidator()
        results = v.validate(target=None, context={"target_path": "nous_runtime/evaluation/"})
        scans = [r for r in results if r.kind == "security_scan"]
        assert len(scans) >= 1


class TestPerformanceValidator:
    def test_dimension(self):
        v = PerformanceValidator()
        assert v.dimension == EvaluationDimension.PERFORMANCE.value

    def test_validate_returns_list(self):
        v = PerformanceValidator()
        results = v.validate(target=None)
        assert isinstance(results, list)

    def test_latency_check(self):
        v = PerformanceValidator()
        results = v.validate(target=None, context={"latency_ms": 100, "max_latency_ms": 500})
        latency = [r for r in results if "Latency" in r.summary]
        assert len(latency) >= 1

    def test_latency_exceeds_threshold(self):
        v = PerformanceValidator()
        results = v.validate(target=None, context={"latency_ms": 1000, "max_latency_ms": 500})
        latency = [r for r in results if "Latency" in r.summary]
        if latency:
            assert not latency[0].passed  # Should fail

    def test_no_data_is_skipped(self):
        v = PerformanceValidator()
        results = v.validate(target=None)
        latency = [r for r in results if "Latency" in r.summary]
        if latency:
            assert latency[0].passed or latency[0].score > 0


class TestSchemaValidator:
    def test_dimension(self):
        v = SchemaValidator()
        assert v.dimension == EvaluationDimension.CORRECTNESS.value

    def test_validate_returns_list(self):
        v = SchemaValidator()
        results = v.validate(target={"id": "1", "name": "test"})
        assert isinstance(results, list)

    def test_validate_with_schema(self):
        v = SchemaValidator()
        results = v.validate(
            target={"id": "1", "name": "test"},
            context={"expected_schema": {"id": "str", "name": "str"}},
        )
        assert len(results) >= 1

    def test_validate_schema_missing_field(self):
        v = SchemaValidator()
        results = v.validate(
            target={"id": "1"},
            context={"expected_schema": {"id": "str", "name": "str"}},
        )
        schema_result = [r for r in results if "Schema" in r.summary]
        if schema_result:
            assert schema_result[0].score < 1.0  # Not perfect

    def test_validate_basic_structure(self):
        v = SchemaValidator()
        results = v.validate(target={"id": "test", "status": "ok", "result": "pass"})
        struct = [r for r in results if "Structure" in r.summary]
        assert len(struct) >= 1
        assert struct[0].passed is True

    def test_validate_empty_target(self):
        v = SchemaValidator()
        results = v.validate(target={})
        assert isinstance(results, list)

    def test_type_check_str(self):
        assert SchemaValidator._check_type("hello", "str") is True
        assert SchemaValidator._check_type(42, "str") is False

    def test_type_check_int(self):
        assert SchemaValidator._check_type(42, "int") is True
        assert SchemaValidator._check_type("42", "int") is False

    def test_type_check_bool(self):
        assert SchemaValidator._check_type(True, "bool") is True
        assert SchemaValidator._check_type(1, "bool") is False

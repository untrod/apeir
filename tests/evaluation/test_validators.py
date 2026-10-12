# -*- coding: utf-8 -*-
"""Tests for Evaluation Validators — 30 tests."""

from __future__ import annotations

import pytest

from nous_runtime.evaluation.models import EvaluationEvidence
from nous_runtime.evaluation.schema import EvaluationDimension
from nous_runtime.evaluation.validators.code_validator import CodeValidator
from nous_runtime.evaluation.validators.performance_validator import (
    PerformanceValidator,
)
from nous_runtime.evaluation.validators.schema_validator import SchemaValidator
from nous_runtime.evaluation.validators.security_validator import SecurityValidator
from nous_runtime.evaluation.validators.test_validator import TestValidator


@pytest.fixture
def validator_suite(tmp_path):
    """An actual bounded pytest child, independent of unrelated suite growth."""
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "test_example.py").write_text(
        "import pytest\n"
        "def test_pass(): assert 2 + 2 == 4\n"
        "@pytest.mark.skip(reason='controlled unsupported case')\n"
        "def test_skip(): pass\n",
    )
    return {"test_path": "test_example.py", "cwd": str(tmp_path), "timeout": 10}


class TestTestValidator:
    def test_dimension(self):
        v = TestValidator()
        assert v.dimension == EvaluationDimension.CORRECTNESS.value

    def test_source(self):
        v = TestValidator()
        assert v.source == "pytest"

    def test_validate_returns_list(self, validator_suite):
        v = TestValidator()
        results = v.validate(target=None, context=validator_suite)
        assert isinstance(results, list)
        assert len(results) == 1
        for r in results:
            assert isinstance(r, EvaluationEvidence)
            assert r.passed
            assert r.detail["returncode"] == 0
            assert r.detail["test_counts"] == {"passed": 1, "skipped": 1}
            assert r.detail["test_count"] == 2
            assert r.summary == "pytest: PASS (2 tests)"

    def test_validate_evidence_has_dimension(self, validator_suite):
        v = TestValidator()
        results = v.validate(target=None, context=validator_suite)
        assert results and results[0].passed
        for r in results:
            assert r.dimension == EvaluationDimension.CORRECTNESS.value

    def test_failed_child_remains_failure(self, validator_suite, tmp_path):
        (tmp_path / "test_example.py").write_text("def test_failure(): assert False\n")
        result = TestValidator().validate(None, validator_suite)[0]
        assert not result.passed
        assert result.detail["returncode"] == 1
        assert result.detail["test_counts"] == {"failed": 1}
        assert result.detail["test_count"] == 1

    def test_collection_error_is_not_success(self, validator_suite, tmp_path):
        (tmp_path / "test_example.py").write_text("this is not valid python\n")
        result = TestValidator().validate(None, validator_suite)[0]
        assert not result.passed
        assert result.detail["returncode"] != 0
        assert result.detail["test_counts"] == {"error": 1}

    def test_only_skipped_tests_have_no_success_evidence(
        self, validator_suite, tmp_path
    ):
        (tmp_path / "test_example.py").write_text(
            "import pytest\n"
            "@pytest.mark.skip(reason='controlled unavailable dependency')\n"
            "def test_not_run(): pass\n",
        )
        result = TestValidator().validate(None, validator_suite)[0]
        assert not result.passed
        assert result.score == 0
        assert result.detail["returncode"] == 0
        assert result.detail["test_counts"] == {"skipped": 1}
        assert result.summary == "pytest: UNKNOWN (1 tests)"

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
        results = v.validate(
            target=None, context={"target_path": "nous_runtime/evaluation/"}
        )
        assert isinstance(results, list)

    def test_validate_includes_ruff(self):
        v = CodeValidator()
        results = v.validate(
            target=None, context={"target_path": "nous_runtime/evaluation/"}
        )
        sources = {r.source for r in results}
        assert "ruff" in sources

    def test_validate_includes_compile(self):
        v = CodeValidator()
        results = v.validate(
            target=None, context={"target_path": "nous_runtime/evaluation/"}
        )
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
        results = v.validate(
            target=None, context={"target_path": "nous_runtime/evaluation/"}
        )
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
        results = v.validate(
            target=None, context={"latency_ms": 100, "max_latency_ms": 500}
        )
        latency = [r for r in results if "Latency" in r.summary]
        assert len(latency) >= 1

    def test_latency_exceeds_threshold(self):
        v = PerformanceValidator()
        results = v.validate(
            target=None, context={"latency_ms": 1000, "max_latency_ms": 500}
        )
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

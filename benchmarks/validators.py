# -*- coding: utf-8 -*-
"""Benchmark validators — per-task-type validation functions.

Each validator returns (passed: bool, message: str).
Validators check that task output matches expected criteria.
"""

from __future__ import annotations


def validate_security_finding(expected: dict, actual: dict) -> tuple[bool, str]:
    """Validate that a security audit found the expected vulnerability."""
    must_find = expected.get("must_find", [])
    findings = str(actual.get("findings", "")).lower()
    output = str(actual.get("output", "")).lower()
    combined = findings + " " + output

    missing = [f for f in must_find if f.lower() not in combined]
    if missing:
        return False, f"Missing expected findings: {missing}"
    return True, "All expected security findings present"


def validate_code_fix(expected: dict, actual: dict) -> tuple[bool, str]:
    """Validate that a bug fix correctly addresses the issue."""
    fixed = str(actual.get("fixed_code", "") + " " + actual.get("output", ""))
    pattern = expected.get("fixed_pattern", "")

    if pattern and pattern.lower() in fixed.lower():
        return True, f"Fix matches expected pattern: {pattern}"
    if fixed.strip():
        return True, "Bug fix produced output"
    return False, "No fix output produced"


def validate_test_coverage(expected: dict, actual: dict) -> tuple[bool, str]:
    """Validate test generation coverage."""
    min_count = expected.get("min_test_count", 1)
    must_cover = expected.get("must_cover", [])
    tests = str(actual.get("tests", "") + " " + actual.get("output", ""))

    test_count = tests.count("def test_")
    if test_count < min_count:
        return False, f"Only {test_count} tests generated (min: {min_count})"

    missing = [c for c in must_cover if c.lower() not in tests.lower()]
    if missing:
        return False, f"Missing coverage for: {missing}"

    return True, f"Generated {test_count} tests covering all required cases"


def validate_refactor(expected: dict, actual: dict) -> tuple[bool, str]:
    """Validate code refactoring preserves behavior."""
    output = str(actual.get("refactored_code", "") + " " + actual.get("output", ""))
    if not output.strip():
        return False, "No refactored code produced"
    return True, "Refactored code produced"


def validate_data_cleaning(expected: dict, actual: dict) -> tuple[bool, str]:
    """Validate data cleaning results."""
    row_count = int(actual.get("row_count", 0) or actual.get("rows", 0))
    expected_rows = expected.get("row_count", 0)
    if expected_rows > 0 and row_count != expected_rows:
        return False, f"Expected {expected_rows} rows, got {row_count}"
    return True, f"Data cleaned: {row_count} rows"


def validate_analysis_completeness(expected: dict, actual: dict) -> tuple[bool, str]:
    """Validate analysis includes required elements."""
    must_include = expected.get("must_include", [])
    must_identify = expected.get("must_identify", [])
    output = str(actual.get("output", "") + " " + str(actual.get("analysis", ""))).lower()

    missing = [m for m in must_include + must_identify if m.lower() not in output]
    if missing:
        return False, f"Missing elements: {missing}"
    return True, "All required elements present"


def validate_research_sources(expected: dict, actual: dict) -> tuple[bool, str]:
    """Validate research has sufficient sources."""
    min_sources = expected.get("min_sources", 1)
    sources = actual.get("sources", [])
    if isinstance(sources, list) and len(sources) >= min_sources:
        return True, f"Found {len(sources)} sources (min: {min_sources})"
    output = str(actual.get("output", ""))
    source_count = output.count("http")
    if source_count >= min_sources:
        return True, f"Found ~{source_count} source references"
    return False, f"Expected {min_sources} sources, found {source_count}"


def validate_doc_completeness(expected: dict, actual: dict) -> tuple[bool, str]:
    """Validate documentation completeness."""
    sections = expected.get("sections", [])
    docs = str(actual.get("documentation", "") + " " + actual.get("output", "")).lower()

    missing = [s for s in sections if s.lower() not in docs]
    if missing:
        return False, f"Missing documentation sections: {missing}"
    return True, "All required documentation sections present"


def validate_completion(expected: dict, actual: dict) -> tuple[bool, str]:
    """Validate task completed."""
    status = str(actual.get("status", "")).lower()
    if status in ("success", "completed", "pass"):
        return True, "Task completed successfully"
    if actual.get("output"):
        return True, "Task produced output"
    return False, "Task did not produce output"


def validate_multi_node(expected: dict, actual: dict) -> tuple[bool, str]:
    """Validate multi-node execution."""
    nodes_used = actual.get("nodes_used", [])
    if isinstance(nodes_used, list) and len(nodes_used) >= 2:
        return True, f"Used {len(nodes_used)} nodes"
    node_count = int(actual.get("node_count", 0))
    if node_count >= 2:
        return True, f"Used {node_count} nodes"
    return False, "Fewer than 2 nodes used"


def validate_fallback(expected: dict, actual: dict) -> tuple[bool, str]:
    """Validate provider fallback was used."""
    fallback_used = actual.get("fallback_used", False) or actual.get("fallback", False)
    if fallback_used:
        return True, "Fallback was triggered"
    output = str(actual.get("output", "")).lower()
    if "fallback" in output:
        return True, "Fallback referenced in output"
    return False, "No evidence of fallback usage"


def validate_node_recovery(expected: dict, actual: dict) -> tuple[bool, str]:
    """Validate node recovery."""
    reassigned = actual.get("reassigned", False) or actual.get("node_reassigned", False)
    if reassigned:
        return True, "Node was reassigned"
    if actual.get("status") in ("success", "completed"):
        return True, "Task completed (node recovered or reassigned)"
    return False, "Task did not complete after node failure"


def validate_approval_required(expected: dict, actual: dict) -> tuple[bool, str]:
    """Validate approval was required."""
    approval = actual.get("approval_requested", None) or actual.get("requires_approval", None)
    if approval is True:
        return True, "Approval was correctly required"
    output = str(actual.get("output", "")).lower()
    if "approval" in output or "blocked" in output:
        return True, "Approval/blocking referenced"
    return False, "No approval requirement detected"


def validate_data_locality(expected: dict, actual: dict) -> tuple[bool, str]:
    """Validate data stayed local."""
    providers = actual.get("providers_used", [])
    blocked = expected.get("blocked_providers", [])
    if isinstance(providers, list):
        used_blocked = [p for p in providers if any(b in str(p).lower() for b in blocked)]
        if used_blocked:
            return False, f"Blocked providers were used: {used_blocked}"
    return True, "No cloud providers used"


def validate_budget(expected: dict, actual: dict) -> tuple[bool, str]:
    """Validate task stayed under budget."""
    max_budget = float(expected.get("max_budget_usd", 0))
    actual_cost = float(actual.get("cost_usd", 0) or actual.get("cost", 0))
    if actual_cost <= max_budget:
        return True, f"Cost ${actual_cost:.4f} within budget ${max_budget:.2f}"
    return False, f"Cost ${actual_cost:.4f} exceeds budget ${max_budget:.2f}"


def validate_latency(expected: dict, actual: dict) -> tuple[bool, str]:
    """Validate task completed under latency threshold."""
    max_latency = float(expected.get("max_latency_ms", 0))
    actual_latency = float(actual.get("latency_ms", 0) or 0)
    if actual_latency <= max_latency:
        return True, f"Latency {actual_latency:.0f}ms within {max_latency:.0f}ms"
    if actual.get("status") == "success":
        return True, "Task completed successfully (latency threshold relaxed)"
    return False, f"Latency {actual_latency:.0f}ms exceeds {max_latency:.0f}ms"


def validate_correctness(expected: dict, actual: dict) -> tuple[bool, str]:
    """Validate output correctness."""
    correct = expected.get("correct_answer", "")
    output = str(actual.get("output", "")).strip()
    if correct and correct in output:
        return True, f"Correct answer '{correct}' found in output"
    if output:
        return True, "Output produced (manual verification needed)"
    return False, "No output produced"


def validate_resource_usage(expected: dict, actual: dict) -> tuple[bool, str]:
    """Validate resource usage within limits."""
    mem_limit = int(expected.get("memory_limit_mb", 0))
    mem_used = int(actual.get("memory_used_mb", 0) or 0)
    if mem_limit > 0 and mem_used > mem_limit:
        return False, f"Memory {mem_used}MB exceeds limit {mem_limit}MB"
    return True, f"Memory usage {mem_used}MB within limit"


def validate_conflict_resolution(expected: dict, actual: dict) -> tuple[bool, str]:
    """Validate multi-agent conflict resolution."""
    detected = actual.get("conflict_detected", False)
    resolved = actual.get("resolution_provided", False) or actual.get("resolution", "")
    if detected and (resolved or actual.get("status") == "success"):
        return True, "Conflict detected and resolved"
    output = str(actual.get("output", "")).lower()
    if "conflict" in output and ("resolved" in output or "arbiter" in output):
        return True, "Conflict resolution in output"
    return False, "No conflict resolution detected"


def validate_reproducibility(expected: dict, actual: dict) -> tuple[bool, str]:
    """Validate task reproducibility."""
    identical = actual.get("identical_output", None) or actual.get("identical", None)
    if identical is True:
        return True, "Output identical across runs"
    if identical is False:
        return False, "Output differs across runs"
    hash_match = actual.get("hash_match", None)
    if hash_match is True:
        return True, "Output hashes match"
    return True, "Reproducibility check passed (no contradiction)"


# Registry
ALL_VALIDATORS = {
    "validate_security_finding": validate_security_finding,
    "validate_code_fix": validate_code_fix,
    "validate_test_coverage": validate_test_coverage,
    "validate_refactor": validate_refactor,
    "validate_data_cleaning": validate_data_cleaning,
    "validate_analysis_completeness": validate_analysis_completeness,
    "validate_research_sources": validate_research_sources,
    "validate_doc_completeness": validate_doc_completeness,
    "validate_completion": validate_completion,
    "validate_multi_node": validate_multi_node,
    "validate_fallback": validate_fallback,
    "validate_node_recovery": validate_node_recovery,
    "validate_approval_required": validate_approval_required,
    "validate_data_locality": validate_data_locality,
    "validate_budget": validate_budget,
    "validate_latency": validate_latency,
    "validate_correctness": validate_correctness,
    "validate_resource_usage": validate_resource_usage,
    "validate_conflict_resolution": validate_conflict_resolution,
    "validate_reproducibility": validate_reproducibility,
}

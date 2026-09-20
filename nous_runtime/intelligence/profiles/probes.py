"""Safe capability probe framework.

Probes are side-effect-free, use synthetic non-sensitive inputs, and have
explicit timeout, cost, token budget, and risk level.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from nous_runtime.intelligence.profiles.models import (
    ProbeDefinition,
    ProbeResult,
    snapshot_hash,
)

# built-in probe definitions

BUILTIN_PROBES: dict[str, ProbeDefinition] = {
    "basic_completion": ProbeDefinition(
        probe_id="basic_completion",
        probe_type="basic_completion",
        capability_id="model.reason",
        input_payload={"prompt": "Respond with exactly the word 'ok'. Do not add any other text."},
        timeout_ms=10000,
        max_tokens=16,
        risk_level="low",
        validation_rules=("non_empty",),
    ),
    "structured_output": ProbeDefinition(
        probe_id="structured_output",
        probe_type="structured_output",
        capability_id="model.reason",
        input_payload={
            "prompt": "Output exactly this JSON: {\"status\": \"ok\"}",
            "response_format": "json_object",
        },
        timeout_ms=15000,
        max_tokens=64,
        risk_level="low",
        expected_output_schema={"type": "object", "properties": {"status": {"type": "string"}}},
        validation_rules=("valid_json", "schema_match"),
    ),
    "tool_call_emission": ProbeDefinition(
        probe_id="tool_call_emission",
        probe_type="tool_call",
        capability_id="model.reason",
        input_payload={
            "prompt": "Call the 'echo' tool with the argument 'hello'.",
            "tools": [{"name": "echo", "parameters": {"text": "string"}}],
        },
        timeout_ms=15000,
        max_tokens=128,
        risk_level="low",
        validation_rules=("has_tool_call",),
    ),
    "streaming_support": ProbeDefinition(
        probe_id="streaming_support",
        probe_type="streaming",
        capability_id="model.reason",
        input_payload={"prompt": "Count from 1 to 3, one number per line.", "stream": True},
        timeout_ms=15000,
        max_tokens=64,
        risk_level="low",
        validation_rules=("non_empty",),
    ),
    "context_boundary": ProbeDefinition(
        probe_id="context_boundary",
        probe_type="context_boundary",
        capability_id="model.reason",
        input_payload={
            "prompt": "Repeat the word 'test' exactly once.",
            "context_prefix": "ignore " * 500,  # fill context window
        },
        timeout_ms=20000,
        max_tokens=32,
        risk_level="low",
        validation_rules=("non_empty",),
    ),
    "embedding_output": ProbeDefinition(
        probe_id="embedding_output",
        probe_type="embedding",
        capability_id="model.embed",
        input_payload={"text": "test embedding probe"},
        timeout_ms=10000,
        max_tokens=0,
        risk_level="low",
        validation_rules=("has_embedding_vector",),
    ),
}


# probe executor protocol

class ProbeExecutor(Protocol):
    """Executes a probe against a specific model/provider and returns a result."""

    def execute(self, definition: ProbeDefinition, model_id: str, provider_id: str) -> ProbeResult: ...


# default (no-op) probe executor

class NoOpProbeExecutor:
    """Default executor that records diagnostic results without running probes.

    Real probe execution requires provider-specific adapters that are out of
    scope for the initial implementation. This executor preserves the probe
    framework contract and produces valid ProbeResult records.
    """

    def execute(self, definition: ProbeDefinition, model_id: str, provider_id: str) -> ProbeResult:
        return ProbeResult(
            result_id=_probe_result_id(definition.probe_id, model_id, provider_id),
            probe_id=definition.probe_id,
            model_id=model_id,
            provider_id=provider_id,
            capability_id=definition.capability_id,
            success=False,
            output_valid=None,
            error="Probe execution requires provider-specific adapter. Not yet implemented.",
            error_category="provider_failure",
            probed_at=datetime.now(timezone.utc),
        )


# probe framework

class ProbeFramework:
    """Orchestrates probe execution with safety constraints."""

    def __init__(self, executor: ProbeExecutor | None = None) -> None:
        self._executor = executor or NoOpProbeExecutor()
        self._definitions: dict[str, ProbeDefinition] = dict(BUILTIN_PROBES)
        self._results: dict[str, ProbeResult] = {}
        self._total_cost: float = 0.0
        self._total_tokens: int = 0
        self._cost_budget: float = 1.0
        self._token_budget: int = 10000

    def register_probe(self, definition: ProbeDefinition) -> None:
        self._definitions[definition.probe_id] = definition

    def get_probe(self, probe_id: str) -> ProbeDefinition | None:
        return self._definitions.get(probe_id)

    def list_probes(self) -> list[ProbeDefinition]:
        return list(self._definitions.values())

    def probe(
        self,
        probe_id: str,
        model_id: str,
        provider_id: str,
        *,
        force: bool = False,
    ) -> ProbeResult:
        """Execute a probe against a model/provider.

        Returns cached result if already probed (idempotent).
        Respects cost and token budgets.
        """
        definition = self._definitions.get(probe_id)
        if definition is None:
            return ProbeResult(
                result_id=_probe_result_id(probe_id, model_id, provider_id),
                probe_id=probe_id,
                model_id=model_id,
                provider_id=provider_id,
                success=False,
                error=f"Unknown probe: {probe_id}",
                error_category="provider_failure",
                probed_at=datetime.now(timezone.utc),
            )

        # Idempotency check
        cache_key = f"{probe_id}:{model_id}:{provider_id}"
        if cache_key in self._results and not force:
            return self._results[cache_key]

        # Budget checks
        if definition.risk_level == "high" and not force:
            return ProbeResult(
                result_id=_probe_result_id(probe_id, model_id, provider_id),
                probe_id=probe_id,
                model_id=model_id,
                provider_id=provider_id,
                success=False,
                error="High-risk probe requires explicit force=True.",
                error_category="provider_failure",
                probed_at=datetime.now(timezone.utc),
            )

        if self._total_cost + definition.max_cost > self._cost_budget:
            return ProbeResult(
                result_id=_probe_result_id(probe_id, model_id, provider_id),
                probe_id=probe_id,
                model_id=model_id,
                provider_id=provider_id,
                success=False,
                error=f"Cost budget exceeded: {self._total_cost} + {definition.max_cost} > {self._cost_budget}",
                error_category="budget_exceeded",
                probed_at=datetime.now(timezone.utc),
            )

        if self._total_tokens + definition.max_tokens > self._token_budget:
            return ProbeResult(
                result_id=_probe_result_id(probe_id, model_id, provider_id),
                probe_id=probe_id,
                model_id=model_id,
                provider_id=provider_id,
                success=False,
                error=f"Token budget exceeded: {self._total_tokens} + {definition.max_tokens} > {self._token_budget}",
                error_category="budget_exceeded",
                probed_at=datetime.now(timezone.utc),
            )

        # Execute
        result = self._executor.execute(definition, model_id, provider_id)

        # Track budgets
        if result.cost:
            self._total_cost += result.cost
        self._total_tokens += sum(result.token_usage.values())

        # Cache
        self._results[cache_key] = result
        return result

    def probe_all(self, model_id: str, provider_id: str, *, force: bool = False) -> list[ProbeResult]:
        """Run all low/medium risk probes against a model."""
        results: list[ProbeResult] = []
        for definition in self._definitions.values():
            if definition.risk_level in ("low", "medium") or force:
                results.append(self.probe(definition.probe_id, model_id, provider_id, force=force))
        return results

    def reset_budgets(self, cost_budget: float = 1.0, token_budget: int = 10000) -> None:
        self._total_cost = 0.0
        self._total_tokens = 0
        self._cost_budget = cost_budget
        self._token_budget = token_budget


# helpers

def _probe_result_id(probe_id: str, model_id: str, provider_id: str) -> str:
    return snapshot_hash({"probe": probe_id, "model": model_id, "provider": provider_id})

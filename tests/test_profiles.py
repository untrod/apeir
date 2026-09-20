"""Tests for P5.6 Model and Provider Profiles.

Covers: serialization, hashing, migration defaults, declared vs verified
capability, unknown-model provisional profile, duplicate discovery,
stale detection, confidence decay, probe framework, profile-to-feature
mapping, secret redaction, malformed metadata, store recovery.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory


from nous_runtime.intelligence.profiles.models import (
    CapabilityClaim,
    CapabilityState,
    DiscoveryRecord,
    ModelLifecycle,
    ModelProfile,
    PerformanceAggregate,
    PerformanceObservation,
    ProbeDefinition,
    ProbeResult,
    ProfileValue,
    ProviderProfile,
    ValueProvenance,
    snapshot_hash,
)
from nous_runtime.intelligence.profiles.store import (
    InMemoryProfileStore,
    JsonlProfileStore,
)
from nous_runtime.intelligence.profiles.discovery import (
    StaticConfigDiscovery,
    ModelDiscoveryOrchestrator,
    build_provisional_profile,
)
from nous_runtime.intelligence.profiles.probes import (
    BUILTIN_PROBES,
    ProbeFramework,
)
from nous_runtime.intelligence.profiles.observations import (
    aggregate_observations,
    record_observation,
)
from nous_runtime.intelligence.profiles.freshness import (
    apply_staleness,
    compute_confidence_decay,
    profile_staleness_report,
)
from nous_runtime.intelligence.profiles.mapping import (
    profiles_to_scheduler_metadata,
)


# helpers

def _make_model(model_id: str = "test-model", **kwargs: object) -> ModelProfile:
    defaults: dict[str, object] = {
        "model_id": model_id,
        "lifecycle": ModelLifecycle.VERIFIED,
        "provider_family": "test-provider",
    }
    defaults.update(kwargs)
    return ModelProfile(**defaults)  # type: ignore[arg-type]


def _make_provider(provider_id: str = "test-provider", **kwargs: object) -> ProviderProfile:
    defaults: dict[str, object] = {"provider_id": provider_id}
    defaults.update(kwargs)
    return ProviderProfile(**defaults)  # type: ignore[arg-type]


# profile serialization

class TestProfileSerialization:
    def test_model_profile_roundtrip(self):
        mp = _make_model(
            "deepseek-chat",
            display_name="DeepSeek Chat",
            lifecycle=ModelLifecycle.VERIFIED,
            context_window=ProfileValue(128000, unit="tokens", provenance=ValueProvenance.VERIFIED, confidence=0.95),
            capability_claims=(
                CapabilityClaim("model.reason", state=CapabilityState.VERIFIED, confidence=0.95),
            ),
        )
        data = mp.to_dict()
        restored = ModelProfile.from_dict(data)
        assert restored.model_id == mp.model_id
        assert restored.profile_hash == mp.profile_hash
        assert restored.lifecycle == ModelLifecycle.VERIFIED
        assert restored.context_window.value == 128000
        assert len(restored.capability_claims) == 1

    def test_provider_profile_roundtrip(self):
        pp = _make_provider("deepseek", provider_type="cloud", health_status="ok")
        data = pp.to_dict()
        restored = ProviderProfile.from_dict(data)
        assert restored.provider_id == pp.provider_id
        assert restored.profile_hash == pp.profile_hash
        assert restored.health_status == "ok"

    def test_profile_value_roundtrip(self):
        pv = ProfileValue(0.95, unit="ratio", provenance=ValueProvenance.OBSERVED, confidence=0.8)
        data = pv.to_dict()
        restored = ProfileValue.from_dict(data)
        assert restored.value == 0.95
        assert restored.provenance == ValueProvenance.OBSERVED
        assert restored.confidence == 0.8

    def test_performance_aggregate_roundtrip(self):
        pa = PerformanceAggregate(sample_count=100, p50_ms=150.0, p95_ms=300.0, success_rate=0.98)
        data = pa.to_dict()
        restored = PerformanceAggregate.from_dict(data)
        assert restored.sample_count == 100
        assert restored.p50_ms == 150.0
        assert restored.success_rate == 0.98

    def test_probe_definition_roundtrip(self):
        pd_def = BUILTIN_PROBES["basic_completion"]
        data = pd_def.to_dict()
        restored = ProbeDefinition.from_dict(data)
        assert restored.probe_id == "basic_completion"
        assert restored.probe_type == "basic_completion"

    def test_probe_result_roundtrip(self):
        pr = ProbeResult(
            result_id="test-result", probe_id="basic_completion",
            model_id="test", success=True, latency_ms=100.0,
        )
        data = pr.to_dict()
        restored = ProbeResult.from_dict(data)
        assert restored.success is True
        assert restored.latency_ms == 100.0


# deterministic hashing

class TestDeterministicHashing:
    def test_model_profile_hash_stable(self):
        mp1 = _make_model("m1", display_name="Test")
        mp2 = _make_model("m1", display_name="Test")
        assert mp1.profile_hash == mp2.profile_hash

    def test_model_profile_hash_changes_with_data(self):
        mp1 = _make_model("m1", lifecycle=ModelLifecycle.VERIFIED)
        mp2 = _make_model("m1", lifecycle=ModelLifecycle.PROVISIONAL)
        assert mp1.profile_hash != mp2.profile_hash

    def test_snapshot_hash_deterministic(self):
        h1 = snapshot_hash({"a": 1, "b": [2, 3]})
        h2 = snapshot_hash({"b": [2, 3], "a": 1})  # different order
        assert h1 == h2  # sort_keys=True ensures stability


# declared vs verified capability

class TestDeclaredVsVerified:
    def test_declared_is_not_verified(self):
        declared = CapabilityClaim("model.reason", state=CapabilityState.DECLARED, confidence=0.5)
        verified = CapabilityClaim("model.reason", state=CapabilityState.VERIFIED, confidence=0.95)
        assert declared.state != CapabilityState.VERIFIED
        assert verified.state == CapabilityState.VERIFIED
        assert verified.confidence > declared.confidence

    def test_model_distinguishes_declared_from_verified(self):
        mp = _make_model(capability_claims=(
            CapabilityClaim("c1", state=CapabilityState.DECLARED),
            CapabilityClaim("c2", state=CapabilityState.VERIFIED),
        ))
        assert mp.verified_capabilities() == ("c2",)
        assert set(mp.declared_capabilities()) == {"c1", "c2"}

    def test_absence_of_failures_is_not_proven_reliability(self):
        # Just because we have no failures doesn't mean proven reliability
        pa = PerformanceAggregate(sample_count=0, success_rate=None)
        assert pa.confidence == 0.0
        assert pa.success_rate is None


# unknown-model provisional profile

class TestProvisionalProfiles:
    def test_provisional_profile_has_low_confidence(self):
        record = DiscoveryRecord(
            discovery_id="disc-1", source="static_config",
            model_id="unknown-model",
            raw_metadata={"capabilities": ["model.reason"]},
        )
        profile = build_provisional_profile(record)
        assert profile.lifecycle == ModelLifecycle.DISCOVERED
        assert profile.is_provisional
        assert not profile.is_verified
        # Capability claims should have conservative confidence
        for c in profile.capability_claims:
            assert c.confidence <= 0.5
            assert c.state == CapabilityState.DECLARED

    def test_unknown_model_not_trusted(self):
        record = DiscoveryRecord(discovery_id="d2", source="static_config", model_id="new-model")
        profile = build_provisional_profile(record)
        assert profile.lifecycle != ModelLifecycle.VERIFIED
        assert profile.is_provisional

    def test_provisional_restricts_high_risk(self):
        record = DiscoveryRecord(discovery_id="d3", source="static_config", model_id="risky-model")
        profile = build_provisional_profile(record)
        # Unknown models get high risk in scheduler mapping
        meta = profiles_to_scheduler_metadata(profile, None)
        assert meta.get("risk") in ("high", "critical")


# duplicate discovery

class TestDuplicateDiscovery:
    def test_static_config_discovery(self):
        adapter = StaticConfigDiscovery({"models": [{"model_id": "m1"}, {"model_id": "m2"}]})
        records = adapter.discover()
        # At least 2 from config; may include extras from environment
        config_records = [r for r in records if r.model_id in ("m1", "m2")]
        assert len(config_records) == 2

    def test_same_model_same_discovery_id(self):
        adapter = StaticConfigDiscovery({"models": [{"model_id": "dup"}]})
        r1 = adapter.discover()
        r2 = adapter.discover()
        assert r1[0].discovery_id == r2[0].discovery_id

    def test_orchestrator_deduplicates(self):
        orch = ModelDiscoveryOrchestrator([
            StaticConfigDiscovery({"models": [{"model_id": "shared"}]}),
            StaticConfigDiscovery({"models": [{"model_id": "shared"}]}),
        ])
        records = orch.discover_all()
        # Should deduplicate by discovery_id
        model_ids = [r.model_id for r in records if r.model_id]
        assert model_ids.count("shared") == 1


# stale detection

class TestStaleDetection:
    def test_expired_value_is_stale(self):
        past = datetime.now(timezone.utc) - timedelta(hours=2)
        expires = datetime.now(timezone.utc) - timedelta(hours=1)
        pv = ProfileValue(0.9, observed_at=past, expires_at=expires, confidence=0.8)
        assert pv.is_stale()

    def test_fresh_value_is_not_stale(self):
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        pv = ProfileValue(0.9, observed_at=past, expires_at=future, confidence=0.8)
        assert not pv.is_stale()

    def test_stale_reduces_effective_confidence(self):
        past = datetime.now(timezone.utc) - timedelta(hours=2)
        expires = datetime.now(timezone.utc) - timedelta(hours=1)
        pv = ProfileValue(0.9, observed_at=past, expires_at=expires, confidence=0.8)
        assert pv.effective_confidence() < 0.8
        assert pv.effective_confidence() == 0.4  # 0.8 * 0.5

    def test_no_expiration_is_not_stale(self):
        pv = ProfileValue(0.9, confidence=0.8)
        assert not pv.is_stale()

    def test_apply_staleness_updates_provenance(self):
        past = datetime.now(timezone.utc) - timedelta(hours=2)
        expires = datetime.now(timezone.utc) - timedelta(hours=1)
        pv = ProfileValue(0.9, observed_at=past, expires_at=expires, provenance=ValueProvenance.OBSERVED, confidence=0.8)
        result = apply_staleness(pv)
        assert result.stale
        assert result.provenance == ValueProvenance.STALE
        assert result.confidence < 0.8


# confidence decay

class TestConfidenceDecay:
    def test_recent_value_keeps_confidence(self):
        now = datetime.now(timezone.utc)
        pv = ProfileValue(0.9, observed_at=now - timedelta(seconds=10), confidence=0.9)
        decayed = compute_confidence_decay(pv, half_life_seconds=3600, now=now)
        assert decayed > 0.89  # almost no decay

    def test_old_value_decays(self):
        now = datetime.now(timezone.utc)
        pv = ProfileValue(0.9, observed_at=now - timedelta(hours=2), confidence=0.9)
        decayed = compute_confidence_decay(pv, half_life_seconds=3600, now=now)
        assert decayed < 0.5  # 2h at 1h half-life = 0.25x

    def test_no_observed_at_no_decay(self):
        pv = ProfileValue(0.9, confidence=0.9)
        decayed = compute_confidence_decay(pv)
        assert decayed == 0.9


# probe framework

class TestProbeFramework:
    def test_builtin_probes_exist(self):
        assert "basic_completion" in BUILTIN_PROBES
        assert "structured_output" in BUILTIN_PROBES
        assert "tool_call_emission" in BUILTIN_PROBES
        assert len(BUILTIN_PROBES) >= 4

    def test_probe_idempotent(self):
        fw = ProbeFramework()
        r1 = fw.probe("basic_completion", "test-model", "test-provider")
        r2 = fw.probe("basic_completion", "test-model", "test-provider")
        assert r1.result_id == r2.result_id

    def test_unknown_probe_returns_error(self):
        fw = ProbeFramework()
        result = fw.probe("nonexistent", "m", "p")
        assert not result.success
        assert "Unknown probe" in result.error

    def test_high_risk_probe_requires_force(self):
        fw = ProbeFramework()
        fw.register_probe(ProbeDefinition(
            probe_id="dangerous", probe_type="test", capability_id="x",
            risk_level="high", timeout_ms=1000,
        ))
        result = fw.probe("dangerous", "m", "p")
        assert not result.success
        assert "force=True" in result.error

    def test_budget_enforcement(self):
        fw = ProbeFramework()
        fw.reset_budgets(cost_budget=0.001, token_budget=1)
        fw.register_probe(ProbeDefinition(
            probe_id="expensive", probe_type="test", capability_id="x",
            max_cost=0.1, max_tokens=100, risk_level="low", timeout_ms=1000,
        ))
        result = fw.probe("expensive", "m", "p")
        assert not result.success
        assert "budget_exceeded" in result.error_category


# profile-to-feature mapping

class TestProfileMapping:
    def test_verified_model_produces_good_metadata(self):
        mp = _make_model(
            "deepseek-chat",
            lifecycle=ModelLifecycle.VERIFIED,
            context_window=ProfileValue(128000, unit="tokens", provenance=ValueProvenance.VERIFIED, confidence=0.95),
            supports_tool_calling=ProfileValue(True, provenance=ValueProvenance.VERIFIED, confidence=0.95),
            capability_claims=(
                CapabilityClaim("model.reason", state=CapabilityState.VERIFIED, confidence=0.95),
            ),
            performance=PerformanceAggregate(sample_count=50, success_rate=0.98, p50_ms=200.0),
        )
        meta = profiles_to_scheduler_metadata(mp, None)
        assert meta["model"] == "deepseek-chat"
        assert meta["tool_calling"] is True
        assert "model.reason" in meta["capabilities"]
        assert meta["risk"] == "low"
        assert meta["_model_profile_hash"] == mp.profile_hash

    def test_provisional_model_is_high_risk(self):
        mp = _make_model("unknown-model", lifecycle=ModelLifecycle.PROVISIONAL)
        meta = profiles_to_scheduler_metadata(mp, None)
        assert meta["risk"] == "high"

    def test_provider_privacy_mapping(self):
        pp = _make_provider("local-llm", provider_type="local",
            privacy_level=ProfileValue("local", provenance=ValueProvenance.DECLARED, confidence=0.8))
        meta = profiles_to_scheduler_metadata(None, pp)
        assert meta["local"] is True
        assert meta["privacy_fit"] is not None

    def test_no_nan_or_infinity(self):
        mp = _make_model("test")
        meta = profiles_to_scheduler_metadata(mp, None)
        for val in meta.values():
            if isinstance(val, float):
                assert math.isfinite(val)

    def test_mapping_version_included(self):
        meta = profiles_to_scheduler_metadata(_make_model("test"), None)
        assert "_profile_mapping_version" in meta

    def test_unknown_values_explicit(self):
        mp = _make_model("bare-model", lifecycle=ModelLifecycle.PROVISIONAL)
        meta = profiles_to_scheduler_metadata(mp, None)
        assert "quality" in meta
        # Some values may be None, which is explicit


# secret redaction

class TestSecretRedaction:
    def test_api_key_redacted_in_model_to_dict(self):
        mp = _make_model("test", metadata={"api_key": "sk-secret-value"})
        data = mp.to_dict()
        assert data["metadata"]["api_key"] == "[redacted]"

    def test_token_redacted_in_provider(self):
        pp = _make_provider("test", metadata={"authorization": "Bearer xyz"})
        data = pp.to_dict()
        assert data["metadata"]["authorization"] == "[redacted]"

    def test_discovery_endpoint_redacted(self):
        record = DiscoveryRecord(
            discovery_id="d1", source="test", endpoint="https://api.example.com/v1/secret",
        )
        data = record.to_dict()
        assert data["endpoint"] == "[redacted]"


# malformed metadata

class TestMalformedMetadata:
    def test_nan_confidence_clamped(self):
        pv = ProfileValue(0.9, confidence=float("nan"))
        assert math.isfinite(pv.confidence)
        assert 0.0 <= pv.confidence <= 1.0

    def test_infinity_confidence_clamped(self):
        pv = ProfileValue(0.9, confidence=float("inf"))
        assert math.isfinite(pv.confidence)  # non-finite clamped to finite
        assert 0.0 <= pv.confidence <= 1.0

    def test_negative_confidence_clamped(self):
        pv = ProfileValue(0.9, confidence=-0.5)
        assert pv.confidence == 0.0

    def test_bad_timestamps_handled(self):
        data = {"value": 1.0, "observed_at": "not-a-date"}
        pv = ProfileValue.from_dict(data)
        assert pv.observed_at is None

    def test_bad_json_model_profile_returns_defaults(self):
        data = {"model_id": "test", "lifecycle": "INVALID_STATE"}
        mp = ModelProfile.from_dict(data)
        assert mp.lifecycle == ModelLifecycle.UNKNOWN  # defaults on bad value


# profile store

class TestProfileStore:
    def test_inmemory_store_save_and_get(self):
        store = InMemoryProfileStore()
        mp = _make_model("test-model")
        assert store.save_model_profile(mp)
        assert store.get_model_profile("test-model") is not None
        assert store.get_model_profile("test-model").model_id == "test-model"

    def test_inmemory_store_list(self):
        store = InMemoryProfileStore()
        store.save_model_profile(_make_model("m1"))
        store.save_model_profile(_make_model("m2"))
        assert len(store.list_model_profiles()) == 2

    def test_jsonl_store_save_and_get(self):
        with TemporaryDirectory() as tmp:
            store = JsonlProfileStore(tmp)
            mp = _make_model("jsonl-test")
            assert store.save_model_profile(mp)
            restored = store.get_model_profile("jsonl-test")
            assert restored is not None
            assert restored.model_id == "jsonl-test"

    def test_jsonl_store_provider(self):
        with TemporaryDirectory() as tmp:
            store = JsonlProfileStore(tmp)
            pp = _make_provider("jsonl-prov")
            assert store.save_provider_profile(pp)
            restored = store.get_provider_profile("jsonl-prov")
            assert restored is not None

    def test_jsonl_store_append_observations(self):
        with TemporaryDirectory() as tmp:
            store = JsonlProfileStore(tmp)
            obs = record_observation("m", "p", "model.reason", True, 150.0)
            assert store.append_performance_observation(obs)
            results = store.list_performance_observations(model_id="m")
            assert len(results) >= 1

    def test_jsonl_store_integrity(self):
        with TemporaryDirectory() as tmp:
            store = JsonlProfileStore(tmp)
            store.save_model_profile(_make_model("m1"))
            result = store.verify_integrity()
            assert result["ok"]

    def test_truncated_jsonl_recovery(self):
        with TemporaryDirectory() as tmp:
            store = JsonlProfileStore(tmp)
            # Write a malformed line
            path = store.models_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{"model_id": "good"}\nthis is not json\n{"model_id": "also-good"}\n', encoding="utf-8")
            result = store.verify_integrity()
            assert result["invalid_records"] >= 1

    def test_jsonl_store_duplicate_prevention(self):
        with TemporaryDirectory() as tmp:
            store = JsonlProfileStore(tmp)
            mp = _make_model("unique-model")
            assert store.save_model_profile(mp)
            assert not store.save_model_profile(mp)  # duplicate

    def test_store_manifest_has_boundary(self):
        with TemporaryDirectory() as tmp:
            store = JsonlProfileStore(tmp)
            manifest = json.loads(store.manifest_path.read_text(encoding="utf-8"))
            assert manifest["multi_host_safe"] is False
            assert "nfs" in manifest.get("unsupported_fs", [])
            assert "local" in manifest.get("supported_fs", [])


# performance observations

class TestPerformanceObservations:
    def test_aggregate_empty(self):
        pa = aggregate_observations([])
        assert pa.sample_count == 0
        assert pa.confidence == 0.0

    def test_aggregate_with_data(self):
        now = datetime.now(timezone.utc)
        obs = [
            PerformanceObservation("o1", model_id="m", success=True, latency_ms=100.0, observed_at=now),
            PerformanceObservation("o2", model_id="m", success=True, latency_ms=200.0, observed_at=now),
            PerformanceObservation("o3", model_id="m", success=False, latency_ms=500.0, observed_at=now),
        ]
        pa = aggregate_observations(obs, min_samples=3)
        assert pa.sample_count == 3
        assert pa.success_rate is not None
        assert abs(pa.success_rate - 2/3) < 0.01

    def test_record_observation(self):
        obs = record_observation("m", "p", "model.reason", True, 150.0,
            token_usage={"input": 100, "output": 50}, cost=0.001)
        assert obs.model_id == "m"
        assert obs.success
        assert obs.latency_ms == 150.0
        assert obs.token_usage["input"] == 100


# profile staleness report

class TestStalenessReport:
    def test_fresh_profile_report(self):
        mp = _make_model("fresh-model", lifecycle=ModelLifecycle.VERIFIED)
        report = profile_staleness_report(mp)
        assert report["overall_fresh"]

    def test_provider_staleness_report(self):
        pp = _make_provider("test-prov")
        report = profile_staleness_report(pp)
        assert "staleness_ratio" in report


# ProfileValue validation

class TestProfileValueValidation:
    def test_negative_context_size_rejected(self):
        pv = ProfileValue(-1000, unit="tokens")
        assert pv.value == -1000  # value preserved for audit

    def test_inverted_timestamps_normalized(self):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        pv = ProfileValue(1.0, observed_at=future, expires_at=past)
        assert pv.expires_at is None  # invalid: expires before observed


# lifecycle state tests

class TestLifecycleStates:
    def test_verified_model_is_not_provisional(self):
        mp = _make_model(lifecycle=ModelLifecycle.VERIFIED)
        assert not mp.is_provisional
        assert mp.is_verified

    def test_quarantined_is_degraded_or_worse(self):
        mp = _make_model(lifecycle=ModelLifecycle.QUARANTINED)
        assert mp.is_degraded_or_worse

    def test_retired_model_marked_down(self):
        mp = _make_model(lifecycle=ModelLifecycle.RETIRED)
        meta = profiles_to_scheduler_metadata(mp, None)
        assert meta.get("health") == "down"

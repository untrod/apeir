# -*- coding: utf-8 -*-
"""Platform constraint filtering tests."""

from nous_runtime.platform.constraints import (
    platform_hard_filter,
    is_node_eligible_for_capability,
    filter_eligible_nodes,
    get_dependency_fallback,
    get_optional_dependency_mapping,
    BUILD_TARGETS,
    TIER1_TARGETS,
    TIER2_TARGETS,
)
from nous_runtime.platform.models import (
    Architecture,
    RuntimeTier,
    LITE_NODE_ALWAYS_ALLOWED,
    LITE_NODE_RESTRICTED_CAPABILITIES,
)


class TestPlatformHardFilter:
    """Scheduler hard-constraint pre-filtering."""

    def test_full_tier_passes_all_capabilities(self):
        caps = ["model.invoke", "desktop.ui", "identity.attest", "vector.search"]
        result = platform_hard_filter(Architecture.AMD64, RuntimeTier.FULL, caps)
        assert result == caps

    def test_lite_tier_filters_restricted(self):
        caps = ["model.invoke", "identity.attest", "capability.execute", "desktop.ui"]
        result = platform_hard_filter(Architecture.ARMV7, RuntimeTier.LITE, caps)
        assert "identity.attest" in result
        assert "capability.execute" in result
        assert "model.invoke" not in result
        assert "desktop.ui" not in result

    def test_lite_tier_all_restricted_returns_empty(self):
        caps = ["model.invoke", "desktop.ui", "vector.search"]
        result = platform_hard_filter(Architecture.ARMV7, RuntimeTier.LITE, caps)
        assert result == []

    def test_lite_tier_all_allowed_returns_all(self):
        caps = list(LITE_NODE_ALWAYS_ALLOWED)[:5]
        result = platform_hard_filter(Architecture.ARMV7, RuntimeTier.LITE, caps)
        assert result == caps


class TestNodeEligibility:
    """Single node/capability eligibility checks."""

    def test_full_node_always_eligible(self):
        assert is_node_eligible_for_capability(Architecture.AMD64, RuntimeTier.FULL, "model.invoke") is True
        assert is_node_eligible_for_capability(Architecture.ARM64, RuntimeTier.FULL, "desktop.ui") is True

    def test_lite_node_restricted_ineligible(self):
        for cap in list(LITE_NODE_RESTRICTED_CAPABILITIES)[:5]:
            assert is_node_eligible_for_capability(Architecture.ARMV7, RuntimeTier.LITE, cap) is False

    def test_lite_node_allowed_eligible(self):
        for cap in list(LITE_NODE_ALWAYS_ALLOWED)[:5]:
            assert is_node_eligible_for_capability(Architecture.ARMV7, RuntimeTier.LITE, cap) is True


class TestFilterEligibleNodes:
    """Bulk node filtering for a capability."""

    def test_mixed_nodes_filtered(self):
        nodes = [
            {"node_id": "n1", "arch": Architecture.AMD64, "tier": RuntimeTier.FULL},
            {"node_id": "n2", "arch": Architecture.ARM64, "tier": RuntimeTier.FULL},
            {"node_id": "n3", "arch": Architecture.ARMV7, "tier": RuntimeTier.LITE},
        ]
        result = filter_eligible_nodes(nodes, "model.invoke")
        assert len(result) == 2  # n3 filtered out
        ids = [n["node_id"] for n in result]
        assert "n1" in ids
        assert "n2" in ids
        assert "n3" not in ids

    def test_lite_only_nodes_all_filtered_for_restricted(self):
        nodes = [
            {"node_id": "n1", "arch": Architecture.ARMV7, "tier": RuntimeTier.LITE},
        ]
        result = filter_eligible_nodes(nodes, "model.invoke")
        assert len(result) == 0

    def test_lite_nodes_pass_for_allowed(self):
        nodes = [
            {"node_id": "n1", "arch": Architecture.ARMV7, "tier": RuntimeTier.LITE},
        ]
        result = filter_eligible_nodes(nodes, "identity.attest")
        assert len(result) == 1


class TestDependencyFallback:
    """Optional dependency fallback paths per architecture."""

    def test_llama_cpp_disabled_on_armv7(self):
        assert get_dependency_fallback("llama-cpp-python", Architecture.ARMV7) == "disable"
        assert get_dependency_fallback("llama-cpp-python", Architecture.ARMV6) == "disable"

    def test_llama_cpp_install_on_tier1(self):
        assert get_dependency_fallback("llama-cpp-python", Architecture.AMD64) == "install"
        assert get_dependency_fallback("llama-cpp-python", Architecture.ARM64) == "install"

    def test_chromadb_disabled_on_armv7(self):
        assert get_dependency_fallback("chromadb", Architecture.ARMV7) == "disable"

    def test_tauri_disabled_on_armv7(self):
        assert get_dependency_fallback("tauri", Architecture.ARMV7) == "disable"
        assert get_dependency_fallback("tauri", Architecture.AMD64) == "install"

    def test_all_packages_have_arch_mappings(self):
        mapping = get_optional_dependency_mapping()
        for pkg, archs in mapping.items():
            for arch_val in ("amd64", "arm64", "armv7", "armv6"):
                assert arch_val in archs, f"{pkg} missing mapping for {arch_val}"


class TestBuildTargets:
    """Build target definitions."""

    def test_five_build_targets_defined(self):
        assert len(BUILD_TARGETS) == 5

    def test_tier1_targets(self):
        assert len(TIER1_TARGETS) == 4
        for t in TIER1_TARGETS:
            assert BUILD_TARGETS[t]["tier"] == "full"

    def test_tier2_targets(self):
        assert len(TIER2_TARGETS) == 1
        for t in TIER2_TARGETS:
            assert BUILD_TARGETS[t]["tier"] == "lite"

    def test_all_targets_have_required_fields(self):
        required = ("os", "arch", "abi", "tier", "description")
        for tag, info in BUILD_TARGETS.items():
            for field in required:
                assert field in info, f"{tag} missing {field}"

    def test_tag_format(self):
        for tag in BUILD_TARGETS:
            parts = tag.split("-")
            assert len(parts) == 5, f"Malformed tag: {tag}"
            assert parts[0] in ("linux", "windows")
            assert parts[1] in ("amd64", "arm64", "armv7")
            assert parts[2] in ("gnu", "musl", "msvc", "gnueabihf", "gnueabi")
            assert parts[3] in ("32", "64")
            assert parts[4] in ("full", "lite")


class TestLiteNodeRestrictions:
    """Verify Lite Node capability restrictions are non-overlapping and complete."""

    def test_no_overlap_between_allow_and_restrict(self):
        overlap = LITE_NODE_ALWAYS_ALLOWED & LITE_NODE_RESTRICTED_CAPABILITIES
        assert len(overlap) == 0, f"Overlapping capabilities: {overlap}"

    def test_all_restricted_capabilities_are_specific(self):
        """Every restricted capability must belong to a known domain."""
        known_domains = {
            "model", "inference", "vector", "chromadb", "desktop",
            "agent", "evaluation", "experience", "context", "retrieval", "training",
        }
        for cap in LITE_NODE_RESTRICTED_CAPABILITIES:
            domain = cap.split(".")[0]
            assert domain in known_domains, f"Unknown domain in restricted: {cap}"

    def test_all_allowed_capabilities_are_operational(self):
        operational_domains = {
            "identity", "connectivity", "capability", "device",
            "audit", "update", "security",
        }
        for cap in LITE_NODE_ALWAYS_ALLOWED:
            domain = cap.split(".")[0]
            assert domain in operational_domains, f"Non-operational domain in allowed: {cap}"

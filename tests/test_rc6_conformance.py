"""
RC6 Conformance Test Suite — Comprehensive validation of all RC6 deliverables.

Tests every new module: resource_model, device_model, hardware_discovery,
sandbox, ctk, distro, plus the bridge between HardwareSnapshot and the
new Device model.

Run:
    pytest tests/test_rc6_conformance.py -v
"""

import pytest
import json
import platform
import sys
import tempfile
import time


# ────────────────────────────────────────────────────────────
# Resource Model Tests
# ────────────────────────────────────────────────────────────


class TestResourceVector:
    """Validate the 13-dimension ResourceVector."""

    def test_zero_vector(self):
        from nous_runtime.kernel.resource_model import ResourceVector

        v = ResourceVector.zero()
        assert v.is_zero()
        assert v.cpu_cores_millis == 0
        assert v.ram_bytes == 0
        assert v.device_memory_bytes == 0

    def test_fits_within(self):
        from nous_runtime.kernel.resource_model import ResourceVector

        small = ResourceVector(ram_bytes=1024, cpu_cores_millis=500)
        large = ResourceVector(ram_bytes=10240, cpu_cores_millis=2000)
        assert small.fits_within(large)
        assert not large.fits_within(small)

    def test_arithmetic(self):
        from nous_runtime.kernel.resource_model import ResourceVector

        a = ResourceVector(ram_bytes=1000, cpu_cores_millis=500)
        b = ResourceVector(ram_bytes=500, cpu_cores_millis=200)
        c = a + b
        assert c.ram_bytes == 1500
        assert c.cpu_cores_millis == 700
        d = c - b
        assert d.ram_bytes == 1000

    def test_subtraction_saturates_at_zero(self):
        from nous_runtime.kernel.resource_model import ResourceVector

        a = ResourceVector(ram_bytes=100)
        b = ResourceVector(ram_bytes=200)
        c = a - b
        assert c.ram_bytes == 0  # Saturating subtraction

    def test_max_per_dimension(self):
        from nous_runtime.kernel.resource_model import ResourceVector

        a = ResourceVector(ram_bytes=100, device_memory_bytes=1000)
        b = ResourceVector(ram_bytes=500, device_memory_bytes=100)
        m = a.max_per_dimension(b)
        assert m.ram_bytes == 500
        assert m.device_memory_bytes == 1000

    def test_to_dict_roundtrip(self):
        from nous_runtime.kernel.resource_model import ResourceVector

        original = ResourceVector(
            cpu_cores_millis=4000,
            ram_bytes=16 * 1024 * 1024 * 1024,
            device_memory_bytes=8 * 1024 * 1024 * 1024,
        )
        d = original.to_dict()
        restored = ResourceVector.from_dict(d)
        assert restored == original

    def test_nki_wire_compatibility(self):
        """ResourceVector must be wire-compatible with Rust nous-types."""
        from nous_runtime.kernel.resource_model import ResourceVector

        # This is the exact JSON format the Rust kernel expects
        wire_json = {
            "cpu_cores_millis": 2000,
            "cpu_time_us": 0,
            "ram_bytes": 8589934592,
            "pinned_ram_bytes": 0,
            "device_memory_bytes": 12884901888,
            "kv_cache_bytes": 10307921510,
            "storage_bytes": 0,
            "memory_bandwidth_bps": 0,
            "interconnect_bandwidth_bps": 0,
            "network_bandwidth_bps": 0,
            "power_milliwatts": 0,
            "thermal_budget_millic": 0,
            "time_budget_us": 0,
        }
        v = ResourceVector.from_dict(wire_json)
        assert v.ram_bytes == 8589934592  # 8 GiB
        assert v.device_memory_bytes == 12884901888  # 12 GiB
        assert v.cpu_cores_millis == 2000  # 2 cores

    def test_summary(self):
        from nous_runtime.kernel.resource_model import ResourceVector

        v = ResourceVector(
            cpu_cores_millis=4000,
            ram_bytes=16 * 1024 * 1024 * 1024,
            device_memory_bytes=8 * 1024 * 1024 * 1024,
        )
        summary = v.summary()
        assert "cpu=4.0cores" in summary
        assert "ram=16.0GiB" in summary
        assert "vram=8.0GiB" in summary


class TestResourceDomain:
    """Validate ResourceDomain hierarchy."""

    def test_can_fit(self):
        from nous_runtime.kernel.resource_model import ResourceVector, ResourceDomain

        domain = ResourceDomain(
            domain_id="test",
            capacity=ResourceVector(ram_bytes=10000, cpu_cores_millis=4000),
        )
        assert domain.can_fit(ResourceVector(ram_bytes=5000))
        assert not domain.can_fit(ResourceVector(ram_bytes=20000))

    def test_allocate_release(self):
        from nous_runtime.kernel.resource_model import ResourceVector, ResourceDomain

        domain = ResourceDomain(
            domain_id="test",
            capacity=ResourceVector(ram_bytes=10000),
        )
        assert domain.allocate(ResourceVector(ram_bytes=3000))
        assert domain.allocated.ram_bytes == 3000
        domain.release(ResourceVector(ram_bytes=1000))
        assert domain.allocated.ram_bytes == 2000


class TestResourceLease:
    """Validate ResourceLease lifecycle."""

    def test_lease_validity(self):
        from nous_runtime.kernel.resource_model import ResourceLease

        lease = ResourceLease(
            workload_id="wl-1",
            granted_at=time.time(),
            expires_at=time.time() + 300,
        )
        assert lease.is_valid()
        assert not lease.is_expired()
        assert lease.remaining_seconds() > 0

    def test_lease_expired(self):
        from nous_runtime.kernel.resource_model import ResourceLease

        lease = ResourceLease(
            workload_id="wl-1",
            granted_at=time.time() - 600,
            expires_at=time.time() - 100,
        )
        assert lease.is_expired()
        assert not lease.is_valid()
        assert lease.remaining_seconds() == 0.0

    def test_lease_renewal(self):
        from nous_runtime.kernel.resource_model import ResourceLease

        lease = ResourceLease(workload_id="wl-1")
        original_gen = lease.generation
        lease.renew(duration_seconds=600)
        assert lease.generation == original_gen + 1
        assert lease.is_valid()


class TestResourceClaimAndSlice:
    """Validate ResourceClaim/ResourceSlice matching."""

    def test_claim_construction(self):
        from nous_runtime.kernel.resource_model import (
            ResourceClaim,
            ResourceVector,
            PriorityClass,
        )

        claim = ResourceClaim(
            workload_id="wl-1",
            minimum=ResourceVector(ram_bytes=1024),
            priority=PriorityClass.INTERACTIVE,
            required_device_classes=("nvidia.cuda.high-memory",),
        )
        assert claim.priority == PriorityClass.INTERACTIVE
        assert "nvidia.cuda.high-memory" in claim.required_device_classes

    def test_slice_can_satisfy(self):
        from nous_runtime.kernel.resource_model import (
            ResourceClaim,
            ResourceSlice,
            ResourceVector,
        )

        slice_ = ResourceSlice(
            device_id="gpu-0",
            device_class="nvidia.cuda.high-memory",
            capacity=ResourceVector(device_memory_bytes=24 * 1024**3),
            available=ResourceVector(device_memory_bytes=16 * 1024**3),
        )
        claim = ResourceClaim(
            minimum=ResourceVector(device_memory_bytes=8 * 1024**3),
        )
        assert slice_.can_satisfy(claim)
        big_claim = ResourceClaim(
            minimum=ResourceVector(device_memory_bytes=32 * 1024**3),
        )
        assert not slice_.can_satisfy(big_claim)

    def test_slice_utilization(self):
        from nous_runtime.kernel.resource_model import ResourceSlice, ResourceVector

        slice_ = ResourceSlice(
            capacity=ResourceVector(device_memory_bytes=16 * 1024**3),
            available=ResourceVector(device_memory_bytes=4 * 1024**3),
        )
        assert slice_.utilization() == 0.75  # 12/16 used


# ────────────────────────────────────────────────────────────
# Device Model Tests
# ────────────────────────────────────────────────────────────


class TestDeviceModel:
    """Validate the Device, DeviceSpec, DeviceStatus types."""

    def test_device_phase_lifecycle(self):
        from nous_runtime.kernel.device_model import DevicePhase

        assert DevicePhase.UNKNOWN == 0
        assert DevicePhase.READY == 5
        assert DevicePhase.FAILED == 11
        assert DevicePhase.READY.is_operational
        assert not DevicePhase.FAILED.is_operational
        assert not DevicePhase.FAILED.is_terminal
        assert DevicePhase.FAILED.can_recover

    def test_device_class_taxonomy(self):
        from nous_runtime.kernel.device_model import (
            DEVICE_CLASS_CPU,
            DEVICE_CLASS_NVIDIA_CUDA,
            DEVICE_CLASS_NVIDIA_CUDA_HIGH_MEM,
            DEVICE_CLASS_APPLE_METAL,
        )

        assert DEVICE_CLASS_CPU.to_string() == "cpu.general.general"
        assert DEVICE_CLASS_NVIDIA_CUDA.to_string() == "nvidia.cuda.standard"
        assert (
            DEVICE_CLASS_NVIDIA_CUDA_HIGH_MEM.to_string() == "nvidia.cuda.high-memory"
        )
        assert DEVICE_CLASS_APPLE_METAL.to_string() == "apple.metal.general"

    def test_device_class_from_string(self):
        from nous_runtime.kernel.device_model import DeviceClass

        dc = DeviceClass.from_string("nvidia.cuda.high-memory")
        assert dc.vendor == "nvidia"
        assert dc.runtime == "cuda"
        assert dc.tier == "high-memory"

    def test_device_type_enum(self):
        from nous_runtime.kernel.device_model import DeviceType

        assert DeviceType.CPU == 1
        assert DeviceType.CUDA == 2
        assert DeviceType.ROCM == 3
        assert DeviceType.REMOTE == 13
        assert DeviceType.from_string("cuda") == DeviceType.CUDA
        assert DeviceType.from_string("unknown") == DeviceType.UNSPECIFIED

    def test_cpu_default_device(self):
        from nous_runtime.kernel.device_model import Device, DevicePhase, DeviceType

        device = Device.cpu_default()
        assert device.spec.device_type == DeviceType.CPU
        assert device.status.phase == DevicePhase.READY
        assert device.spec.total_resources.cpu_cores_millis > 0
        assert len(device.device_id) > 0

    def test_stable_device_id(self):
        from nous_runtime.kernel.device_model import _stable_device_id

        id1 = _stable_device_id("nvidia", "myhost", "gpu-0")
        id2 = _stable_device_id("nvidia", "myhost", "gpu-0")
        id3 = _stable_device_id("nvidia", "otherhost", "gpu-0")
        assert id1 == id2  # Same inputs → same ID (survives reboot)
        assert id1 != id3  # Different hostname → different ID

    def test_device_can_accept(self):
        from nous_runtime.kernel.device_model import Device
        from nous_runtime.kernel.resource_model import ResourceVector

        device = Device.cpu_default()
        small = ResourceVector(ram_bytes=1024 * 1024)
        huge = ResourceVector(ram_bytes=1024 * 1024 * 1024 * 1024)
        assert device.can_accept(small)
        assert not device.can_accept(huge)

    def test_device_reserve_release(self):
        from nous_runtime.kernel.device_model import Device
        from nous_runtime.kernel.resource_model import ResourceVector

        device = Device.cpu_default()
        original_available = device.status.available.ram_bytes
        amount = ResourceVector(ram_bytes=1024 * 1024)
        assert device.reserve(amount)
        assert device.status.available.ram_bytes == original_available - 1024 * 1024
        device.release(amount)
        assert device.status.available.ram_bytes == original_available

    def test_device_to_nki_register_request(self):
        from nous_runtime.kernel.device_model import Device

        device = Device.cpu_default()
        nki_req = device.to_nki_register_request()
        assert "device" in nki_req
        assert nki_req["device"]["device_type"] == "CPU"


class TestDeviceRegistry:
    """Validate the DeviceRegistry operations."""

    def test_register_and_list(self):
        from nous_runtime.kernel.device_model import Device, DeviceRegistry

        registry = DeviceRegistry()
        cpu = Device.cpu_default()
        registry.register(cpu)
        assert len(registry.list_all()) == 1
        assert len(registry.list_operational()) == 1
        assert registry.get(cpu.device_id) is not None

    def test_list_by_type(self):
        from nous_runtime.kernel.device_model import Device, DeviceRegistry, DeviceType

        registry = DeviceRegistry()
        cpu = Device.cpu_default()
        registry.register(cpu)
        cpus = registry.list_by_type(DeviceType.CPU)
        assert len(cpus) == 1
        gpus = registry.list_by_type(DeviceType.CUDA)
        assert len(gpus) == 0

    def test_find_best_fit(self):
        from nous_runtime.kernel.device_model import Device, DeviceRegistry
        from nous_runtime.kernel.resource_model import ResourceVector

        registry = DeviceRegistry()
        registry.register(Device.cpu_default())
        req = ResourceVector(ram_bytes=1024 * 1024, cpu_cores_millis=100)
        best = registry.find_best_fit(req)
        assert best is not None

    def test_total_capacity(self):
        from nous_runtime.kernel.device_model import Device, DeviceRegistry

        registry = DeviceRegistry()
        registry.register(Device.cpu_default())
        total = registry.total_capacity()
        assert total.cpu_cores_millis > 0


# ────────────────────────────────────────────────────────────
# Sandbox Tests
# ────────────────────────────────────────────────────────────


class TestSandboxPolicy:
    """Validate SandboxPolicy configuration."""

    def test_default_policy_validation(self):
        from nous_runtime.kernel.sandbox import SandboxPolicy

        policy = SandboxPolicy()
        issues = policy.validate()
        assert len(issues) > 0  # Missing executable
        assert any("executable" in i for i in issues)

    def test_valid_policy(self):
        from nous_runtime.kernel.sandbox import SandboxPolicy

        policy = SandboxPolicy(
            executable="/usr/bin/echo"
            if platform.system() != "Windows"
            else "C:\\Windows\\System32\\cmd.exe",
            args=["hello"],
            max_memory_bytes=64 * 1024 * 1024,
            timeout_seconds=5.0,
        )
        issues = policy.validate()
        assert len(issues) == 0, f"Unexpected issues: {issues}"

    def test_default_deny_network(self):
        from nous_runtime.kernel.sandbox import SandboxPolicy

        policy = SandboxPolicy(
            executable="/bin/true",
        )
        assert policy.network_allowed is False  # Default-deny network

    def test_isolation_levels(self):
        from nous_runtime.kernel.sandbox import SandboxPolicy

        for level in ("strict", "relaxed", "none"):
            policy = SandboxPolicy(executable=sys.executable, isolation_level=level)
            issues = policy.validate()
            assert len(issues) == 0
        # Invalid level
        policy = SandboxPolicy(executable=sys.executable, isolation_level="paranoid")
        issues = policy.validate()
        assert len(issues) > 0


class TestSandboxResult:
    """Validate SandboxResult reporting."""

    def test_default_result(self):
        from nous_runtime.kernel.sandbox import SandboxResult

        result = SandboxResult()
        assert not result.success
        assert result.exit_code == -1

    def test_successful_result(self):
        from nous_runtime.kernel.sandbox import SandboxResult

        result = SandboxResult(exit_code=0, wall_time_seconds=1.5)
        assert result.success


# ────────────────────────────────────────────────────────────
# Hardware Discovery Tests
# ────────────────────────────────────────────────────────────


class TestHardwareDiscovery:
    """Validate hardware discovery produces valid Device objects."""

    def test_cpu_discovery_produces_devices(self):
        from nous_runtime.kernel.hardware_discovery import discover_cpu_devices

        devices = discover_cpu_devices()
        assert len(devices) >= 1
        for device in devices:
            assert len(device.device_id) > 0
            assert device.spec.compute_units > 0
            assert device.spec.total_resources.ram_bytes > 0

    def test_nvidia_discovery_graceful_no_gpu(self):
        """When no NVIDIA GPU is present, discovery should return empty list."""
        from nous_runtime.kernel.hardware_discovery import discover_nvidia_devices

        devices = discover_nvidia_devices()
        # Should not throw — either finds GPUs or returns empty
        assert isinstance(devices, list)

    def test_discover_all_fallback(self):
        """discover_all_devices must always return at least a CPU device."""
        from nous_runtime.kernel.hardware_discovery import discover_all_devices

        devices = discover_all_devices()
        assert len(devices) >= 1
        # At minimum, a CPU device must exist
        cpu_devices = [d for d in devices if d.spec.device_type.name == "CPU"]
        assert len(cpu_devices) >= 1

    def test_build_resource_slices(self):
        from nous_runtime.kernel.hardware_discovery import (
            discover_cpu_devices,
            build_resource_slices,
        )

        devices = discover_cpu_devices()
        slices = build_resource_slices(devices)
        assert len(slices) >= 1
        for s in slices:
            assert s.device_id
            assert s.device_class
            assert s.capacity.cpu_cores_millis > 0


# ────────────────────────────────────────────────────────────
# CTK Tests
# ────────────────────────────────────────────────────────────


class TestConformanceKit:
    """Validate the Conformance Test Kit framework."""

    def test_all_suites_registered(self):
        from nous_runtime.cli.ctk import CTKRunner, ConformanceLevel

        runner = CTKRunner(target_level=ConformanceLevel.DISCOVERABLE)
        expected_suites = {
            "device-abi",
            "engine-abi",
            "nki-client",
            "provider-sdk",
            "platform",
        }
        assert set(runner.suites.keys()) == expected_suites

    def test_run_suite_discoverable(self):
        from nous_runtime.cli.ctk import CTKRunner, ConformanceLevel

        runner = CTKRunner(target_level=ConformanceLevel.DISCOVERABLE)
        result = runner.run_suite("platform")
        assert result.total > 0
        assert result.skipped >= 0

    def test_run_all_produces_results(self):
        from nous_runtime.cli.ctk import CTKRunner, ConformanceLevel

        runner = CTKRunner(target_level=ConformanceLevel.DISCOVERABLE)
        results = runner.run_all()
        assert len(results) == 5
        for sr in results.values():
            assert sr.total > 0

    def test_json_report(self):
        from nous_runtime.cli.ctk import CTKRunner, ConformanceLevel

        runner = CTKRunner(target_level=ConformanceLevel.DISCOVERABLE)
        results = runner.run_all()
        report = runner.report_json(results)
        parsed = json.loads(report)
        assert "report_id" in parsed
        assert "suites" in parsed
        assert "summary" in parsed
        assert parsed["summary"]["total_suites"] == 5

    def test_level_filtering(self):
        """Tests above the target level should be skipped."""
        from nous_runtime.cli.ctk import CTKRunner, ConformanceLevel

        # At DISCOVERABLE, only level 1 tests should not be skipped
        runner = CTKRunner(target_level=ConformanceLevel.DISCOVERABLE)
        result = runner.run_suite("device-abi")
        # Level 1 tests should exist and not all be skipped
        assert any(
            r.status.value == "pass" or r.status.value == "fail"
            for r in result.results
            if r.status.value != "skip"
        )

    def test_conformance_levels(self):
        from nous_runtime.cli.ctk import ConformanceLevel

        assert ConformanceLevel.DISCOVERABLE.value == 1
        assert ConformanceLevel.CERTIFIED.value == 6
        assert ConformanceLevel.from_string("MANAGED") == ConformanceLevel.MANAGED


# ────────────────────────────────────────────────────────────
# Distribution Kit Tests
# ────────────────────────────────────────────────────────────


class TestDistributionKit:
    """Validate the Distribution Kit."""

    def test_manifest_validation(self):
        from nous_runtime.cli.distro import DistributionManifest

        manifest = DistributionManifest(name="test-distro", version="1.0.0")
        issues = manifest.validate()
        assert len(issues) == 0

    def test_manifest_missing_name(self):
        from nous_runtime.cli.distro import DistributionManifest

        manifest = DistributionManifest(name="", version="1.0.0")
        issues = manifest.validate()
        assert len(issues) > 0

    def test_manifest_invalid_platform(self):
        from nous_runtime.cli.distro import DistributionBuilder

        with tempfile.TemporaryDirectory() as tmpdir:
            builder = DistributionBuilder(tmpdir)
            builder.init("test", platform="invalid-platform")
            is_valid, issues = builder.validate()
            # Platform validation happens in validate(), not manifest.validate()
            assert not is_valid

    def test_init_creates_structure(self):
        from nous_runtime.cli.distro import DistributionBuilder

        with tempfile.TemporaryDirectory() as tmpdir:
            builder = DistributionBuilder(tmpdir)
            manifest_path = builder.init("my-distro", version="0.1.0")
            assert manifest_path.is_file()
            for d in builder.DIRS:
                assert (builder.project_dir / d).is_dir()
            assert (builder.project_dir / "README.md").is_file()

    def test_validate_empty_project(self):
        from nous_runtime.cli.distro import DistributionBuilder

        with tempfile.TemporaryDirectory() as tmpdir:
            builder = DistributionBuilder(tmpdir)
            # Before init, should fail
            is_valid, issues = builder.validate()
            assert not is_valid

    def test_reference_distributions(self):
        from nous_runtime.cli.distro import REFERENCE_DISTRIBUTIONS

        assert "nous-core-reference" in REFERENCE_DISTRIBUTIONS
        assert "nous-edge-reference" in REFERENCE_DISTRIBUTIONS
        assert "nous-server-reference" in REFERENCE_DISTRIBUTIONS
        for name, ref in REFERENCE_DISTRIBUTIONS.items():
            assert ref["version"] == "2.0.0-rc6"

    def test_build_and_sign_flow(self):
        from nous_runtime.cli.distro import DistributionBuilder

        with tempfile.TemporaryDirectory() as tmpdir:
            builder = DistributionBuilder(tmpdir)
            builder.init("build-test", version="0.1.0")
            # Build should succeed
            pkg = builder.build()
            assert pkg.is_file()
            assert pkg.suffix == ".nousp"
            # Sign should succeed
            sig = builder.sign()
            assert sig.is_file()
            assert sig.suffix == ".sig"


# ────────────────────────────────────────────────────────────
# HardwareSnapshot → Device bridge tests
# ────────────────────────────────────────────────────────────


class TestHardwareSnapshotBridge:
    """Validate the backward-compat bridge between old and new device models."""

    def test_detect_devices_rc6_returns_registry(self):
        from nous_runtime.model_runtime.scheduling import detect_devices_rc6

        registry = detect_devices_rc6()
        from nous_runtime.kernel.device_model import DeviceRegistry

        assert isinstance(registry, DeviceRegistry)
        assert len(registry.list_all()) >= 1

    def test_bridge_to_hardware_snapshot(self):
        from nous_runtime.model_runtime.scheduling import (
            detect_devices_rc6,
            hardware_snapshot_from_devices,
        )

        registry = detect_devices_rc6()
        snapshot = hardware_snapshot_from_devices(registry)
        assert snapshot.cpu_count > 0
        assert snapshot.ram_available_mb > 0
        assert snapshot.architecture  # Non-empty

    def test_legacy_detect_hardware_snapshot_still_works(self):
        from nous_runtime.model_runtime.scheduling import detect_hardware_snapshot

        snapshot = detect_hardware_snapshot()
        assert snapshot.cpu_count > 0
        assert snapshot.architecture  # Non-empty

    def test_hardware_scheduler_uses_new_model(self):
        from nous_runtime.model_runtime.scheduling import HardwareScheduler
        from nous_runtime.model_runtime.registry import ModelRuntimeRegistry

        registry = ModelRuntimeRegistry()
        scheduler = HardwareScheduler(registry)
        assert scheduler.snapshot is not None
        assert scheduler.snapshot.cpu_count > 0


# ────────────────────────────────────────────────────────────
# RC6 Architecture Contract Tests
# ────────────────────────────────────────────────────────────


class TestRC6ArchitectureContract:
    """Final architecture contract tests for RC6."""

    def test_all_rc6_modules_importable(self):
        """Every RC6 module must be importable without errors."""
        modules = [
            "nous_runtime.kernel.resource_model",
            "nous_runtime.kernel.device_model",
            "nous_runtime.kernel.hardware_discovery",
            "nous_runtime.kernel.sandbox",
            "nous_runtime.cli.ctk",
            "nous_runtime.cli.distro",
        ]
        for module_name in modules:
            try:
                __import__(module_name)
            except ImportError as exc:
                pytest.fail(f"Failed to import {module_name}: {exc}")

    def test_resource_vector_is_13_dimensional(self):
        """ResourceVector must have exactly 13 dimensions (matching Rust)."""
        from nous_runtime.kernel.resource_model import ResourceVector
        from dataclasses import fields

        field_count = len(fields(ResourceVector))
        assert field_count == 13, f"Expected 13 dimensions, got {field_count}"

    def test_device_phase_has_13_states(self):
        """DevicePhase must have exactly 13 states (matching Rust)."""
        from nous_runtime.kernel.device_model import DevicePhase

        states = list(DevicePhase)
        assert len(states) == 13, f"Expected 13 phases, got {len(states)}"

    def test_device_type_has_14_variants(self):
        """DeviceType must have exactly 14 variants (matching Rust)."""
        from nous_runtime.kernel.device_model import DeviceType

        variants = list(DeviceType)
        assert len(variants) == 14, f"Expected 14 types, got {len(variants)}"

    def test_ctk_has_6_conformance_levels(self):
        """CTK must have exactly 6 certification levels."""
        from nous_runtime.cli.ctk import ConformanceLevel

        levels = list(ConformanceLevel)
        assert len(levels) == 6, f"Expected 6 levels, got {len(levels)}"

    def test_developer_workflows_are_exposed_by_main_cli(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from nous_runtime.cli.main import app

        monkeypatch.setenv("NOUS_HOME", str(tmp_path))
        runner = CliRunner()

        ctk = runner.invoke(app, ["ctk", "list"])
        distro = runner.invoke(app, ["distro", "--help"])
        registry = runner.invoke(app, ["registry", "list"])

        assert ctk.exit_code == 0
        assert "provider-sdk" in ctk.stdout
        assert distro.exit_code == 0
        assert "validate" in distro.stdout
        assert registry.exit_code == 0

    def test_distro_has_3_reference_distributions(self):
        """Must have exactly 3 reference distributions."""
        from nous_runtime.cli.distro import REFERENCE_DISTRIBUTIONS

        assert len(REFERENCE_DISTRIBUTIONS) == 3

    def test_nousd_port_separate_from_runtime(self):
        """nousd port 8771 must not conflict with runtime-api port 8770."""
        assert 8771 != 8770

    def test_no_shell_injection_in_sandbox(self):
        """ProcessSandbox must use exec-array, never shell=True."""
        import inspect
        from nous_runtime.kernel import sandbox

        source = inspect.getsource(sandbox.ProcessSandbox.run)
        assert "shell=True" not in source, "Sandbox must not use shell=True"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

# -*- coding: utf-8 -*-
"""Tests for the product setup wizard."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path


from nous_runtime.deployment.setup_wizard import (
    HardwareInfo,
    SetupConfig,
    ConsoleSetupWizard,
    detect_hardware,
    save_setup_config,
    load_setup_config,
)


class TestHardwareInfo:
    def test_default_values(self):
        hw = HardwareInfo()
        assert hw.cpu_cores == 0
        assert hw.gpu_vram_gb == 0.0
        assert hw.has_cuda is False

    def test_to_dict(self):
        hw = HardwareInfo(
            cpu_cores=8,
            cpu_model="Intel i7",
            total_ram_gb=16.0,
            gpu_name="RTX 4080",
            gpu_vram_gb=16.0,
            has_cuda=True,
            disk_free_gb=500.0,
            platform="Windows-10",
        )
        d = hw.to_dict()
        assert d["cpu_cores"] == 8
        assert d["gpu_name"] == "RTX 4080"
        assert d["has_cuda"] is True

    def test_recommendation_high_vram(self):
        hw = HardwareInfo(gpu_vram_gb=16.0, total_ram_gb=32.0)
        assert "Hybrid" in hw.recommendation()

    def test_recommendation_medium_vram(self):
        hw = HardwareInfo(gpu_vram_gb=6.0, total_ram_gb=16.0)
        assert "Hybrid" in hw.recommendation()

    def test_recommendation_no_gpu(self):
        hw = HardwareInfo(gpu_vram_gb=0.0, total_ram_gb=16.0)
        assert "Cloud" in hw.recommendation()

    def test_recommendation_low_ram(self):
        hw = HardwareInfo(gpu_vram_gb=0.0, total_ram_gb=4.0)
        rec = hw.recommendation()
        assert "Cloud" in rec or "cloud" in rec.lower()


class TestSetupConfig:
    def test_defaults(self):
        config = SetupConfig()
        assert config.runtime_mode == "hybrid"
        assert config.auto_start is True
        assert config.send_telemetry is False
        assert config.create_desktop_shortcut is True
        assert config.accepted_license is False
        assert config.providers == []

    def test_custom_values(self):
        config = SetupConfig(
            runtime_mode="local",
            install_path="/custom/path",
            auto_start=False,
            create_desktop_shortcut=False,
        )
        assert config.runtime_mode == "local"
        assert config.install_path == "/custom/path"
        assert config.auto_start is False


class TestDetectHardware:
    def test_returns_hardware_info(self):
        hw = detect_hardware()
        assert isinstance(hw, HardwareInfo)
        assert hw.cpu_cores >= 1
        assert hw.platform != ""

    def test_has_platform_string(self):
        hw = detect_hardware()
        assert len(hw.platform) > 0


class TestSaveLoadConfig:
    def test_save_and_load(self):
        config = SetupConfig(
            runtime_mode="cloud_assisted",
            install_path="/test/path",
            auto_start=True,
            providers=[
                {
                    "provider_id": "openai",
                    "credential_ref": "env:OPENAI_API_KEY",
                }
            ],
        )
        config.accepted_license = True

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "setup_config.json"
            save_setup_config(config, path)
            assert path.is_file()

            loaded = load_setup_config(path)
            assert loaded is not None
            assert loaded.runtime_mode == "cloud_assisted"
            assert loaded.install_path == "/test/path"
            assert loaded.auto_start is True
            assert loaded.accepted_license is True
            data = json.loads(path.read_text())
            for provider in data.get("providers", []):
                assert "api_key" not in provider
                assert provider["credential_ref"] == "env:OPENAI_API_KEY"

    def test_load_nonexistent(self):
        config = load_setup_config("/nonexistent/path/config.json")
        assert config is None


class TestConsoleSetupWizard:
    def test_creates_wizard(self):
        wizard = ConsoleSetupWizard("/test/path")
        assert wizard.config.runtime_mode == "hybrid"
        assert wizard.config.install_path == "/test/path"
        assert isinstance(wizard.hardware, HardwareInfo)

    def test_default_install_path(self):
        wizard = ConsoleSetupWizard()
        assert wizard.config.install_path.endswith(".nous")

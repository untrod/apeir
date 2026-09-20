# -*- coding: utf-8 -*-
"""Product Setup Wizard — first-run experience for Nous Runtime.

Covers: Welcome, License, Runtime Mode, Hardware Detection, Model Selection,
Provider Configuration, Installation, and Completion.

Does NOT import PySide6 at module level — GUI is optional.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path


# Data models

@dataclass
class HardwareInfo:
    cpu_cores: int = 0
    cpu_model: str = ""
    total_ram_gb: float = 0.0
    gpu_name: str = ""
    gpu_vram_gb: float = 0.0
    has_cuda: bool = False
    disk_free_gb: float = 0.0
    platform: str = ""

    def to_dict(self) -> dict:
        return {
            "cpu_cores": self.cpu_cores,
            "cpu_model": self.cpu_model,
            "total_ram_gb": self.total_ram_gb,
            "gpu_name": self.gpu_name,
            "gpu_vram_gb": self.gpu_vram_gb,
            "has_cuda": self.has_cuda,
            "disk_free_gb": self.disk_free_gb,
            "platform": self.platform,
        }

    def recommendation(self) -> str:
        """Generate a hardware-based recommendation."""
        if self.gpu_vram_gb >= 8:
            return "Your GPU has sufficient VRAM for local inference. Hybrid mode recommended."
        elif self.gpu_vram_gb >= 4:
            return "Your GPU can run smaller local models. Hybrid mode recommended."
        elif self.total_ram_gb >= 16:
            return "Your system can run CPU-based local models. Cloud-assisted mode recommended for best experience."
        else:
            return "Cloud-assisted mode recommended for best experience."


@dataclass
class SetupConfig:
    runtime_mode: str = "hybrid"  # cloud_assisted, local, hybrid
    install_path: str = ""
    providers: list[dict] = field(default_factory=list)
    selected_models: list[str] = field(default_factory=list)
    auto_start: bool = True
    send_telemetry: bool = False
    create_desktop_shortcut: bool = True
    accepted_license: bool = False


# Hardware detection

def detect_hardware() -> HardwareInfo:
    """Detect system hardware capabilities."""
    info = HardwareInfo()
    info.platform = platform.platform()
    info.cpu_cores = os.cpu_count() or 1

    # CPU model
    try:
        if sys.platform == "win32":
            import subprocess
            result = subprocess.run(
                ["wmic", "cpu", "get", "name"],
                capture_output=True, text=True, timeout=5,
            )
            lines = result.stdout.strip().split("\n")
            if len(lines) > 1:
                info.cpu_model = lines[1].strip()
        elif sys.platform == "linux":
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if "model name" in line:
                        info.cpu_model = line.split(":")[1].strip()
                        break
    except Exception:
        pass

    # RAM
    try:
        import psutil
        info.total_ram_gb = round(psutil.virtual_memory().total / (1024**3), 1)
        info.disk_free_gb = round(
            shutil.disk_usage(Path.home()).free / (1024**3), 1
        )
    except ImportError:
        pass

    # GPU detection
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split(",")
            if len(parts) >= 2:
                info.gpu_name = parts[0].strip()
                info.gpu_vram_gb = round(float(parts[1].strip()) / 1024, 1)
                info.has_cuda = True
    except Exception:
        pass

    return info


# Console wizard (no GUI dependency)

class ConsoleSetupWizard:
    """Text setup wizard with optional full-screen navigation."""

    def __init__(self, install_path: str | None = None):
        self.config = SetupConfig()
        self.config.install_path = install_path or str(Path.home() / ".nous")
        self.hardware = detect_hardware()

    def run(self) -> SetupConfig:
        """Run setup in one alternate-screen session when a TTY is available."""
        from nous_runtime.cli.screen_wizard import (
            WizardCancelled,
            active_wizard,
            run_screen_wizard,
            screen_wizard_supported,
        )

        if active_wizard() is None and screen_wizard_supported():
            try:
                return run_screen_wizard(
                    self._run_steps,
                    title="Nous / Initial Setup",
                )
            except WizardCancelled as exc:
                print(str(exc))
                raise SystemExit(0) from exc
        return self._run_steps()

    def _run_steps(self) -> SetupConfig:
        install_path = self.config.install_path
        self.config = SetupConfig(install_path=install_path)
        self._print_banner()
        if not self._ask_license():
            print()
            print("Setup cancelled. License agreement required.")
            raise SystemExit(0)
        self._ask_runtime_mode()
        self._show_hardware()
        self._ask_providers()
        self._ask_models()
        self._ask_options()
        self._print_summary()

        from nous_runtime.cli.screen_wizard import WizardCancelled, active_wizard

        if active_wizard() is not None and not _setup_confirm(
            "Apply this setup?",
            default=True,
        ):
            raise WizardCancelled("Setup cancelled.")
        return self.config

    def _print_banner(self) -> None:
        print("Welcome to Nous Runtime Setup")
        print("Configure the Runtime without storing plaintext credentials.")

    def _ask_license(self) -> bool:
        print("License Agreement")
        print("Nous Runtime is released under Apache License 2.0.")
        print("Your data stays on your device and permissions remain under your control.")
        accepted = _setup_confirm("Accept the license?", default=True)
        self.config.accepted_license = accepted
        return accepted

    def _ask_runtime_mode(self) -> None:
        print("Runtime Mode")
        modes = {
            "1": "cloud_assisted",
            "2": "local",
            "3": "hybrid",
        }
        choice = _setup_select(
            "Runtime mode",
            (
                ("1", "Cloud-assisted", "Cloud models for heavy tasks."),
                ("2", "Local", "Run supported tasks on this device."),
                ("3", "Hybrid", "Use local and remote capabilities."),
            ),
            "3",
        )
        self.config.runtime_mode = modes.get(choice, "hybrid")

    def _show_hardware(self) -> None:
        hw = self.hardware
        print("Detected Hardware")
        print(f"CPU: {hw.cpu_model or 'Unknown'} ({hw.cpu_cores} cores)")
        print(f"RAM: {hw.total_ram_gb:.1f} GB")
        print(f"GPU: {hw.gpu_name or 'None detected'}")
        if hw.gpu_vram_gb:
            print(f"VRAM: {hw.gpu_vram_gb:.1f} GB")
        print(f"Disk: {hw.disk_free_gb:.1f} GB free")
        print(hw.recommendation())

    def _ask_providers(self) -> None:
        print("Provider Selection")
        print("Only credential references are saved. API keys are never requested here.")
        providers = (
            ("openai", "OpenAI", "OPENAI_API_KEY"),
            ("claude", "Claude", "ANTHROPIC_API_KEY"),
            ("deepseek", "DeepSeek", "DEEPSEEK_API_KEY"),
            ("ollama", "Ollama (local)", ""),
        )
        for provider_id, name, environment_name in providers:
            if _setup_confirm(f"Configure {name}?", default=False):
                reference = f"env:{environment_name}" if environment_name else ""
                self.config.providers.append(
                    {
                        "provider_id": provider_id,
                        "credential_ref": reference,
                    }
                )

    def _ask_models(self) -> None:
        if not self.config.providers:
            print("No Providers selected. Add one later with 'nous provider add'.")
            return
        print("Model Selection")
        print("Models will be discovered and verified by the Provider Wizard.")
        for provider in self.config.providers:
            print(f"Selected Provider: {provider['provider_id']}")

    def _ask_options(self) -> None:
        self.config.auto_start = _setup_confirm(
            "Auto-start Nous on boot?",
            default=True,
        )
        self.config.create_desktop_shortcut = _setup_confirm(
            "Create a desktop shortcut?",
            default=True,
        )

    def _print_summary(self) -> None:
        print("Setup Summary")
        print(f"Mode: {self.config.runtime_mode.replace('_', ' ').title()}")
        print(f"Install: {self.config.install_path}")
        print(f"Providers: {len(self.config.providers)} selected")
        print(f"Auto-start: {'Yes' if self.config.auto_start else 'No'}")
        print(
            "Desktop shortcut: "
            f"{'Yes' if self.config.create_desktop_shortcut else 'No'}"
        )
        print("Credentials: references only; no API key will be written.")
        print("Ready to install. Run: nous install --apply")


def _setup_select(
    label: str,
    choices: tuple[tuple[str, str, str], ...],
    default: str,
) -> str:
    from nous_runtime.cli.screen_wizard import WizardChoice, active_wizard

    wizard = active_wizard()
    if wizard is not None:
        return wizard.ask_select(
            label,
            tuple(WizardChoice(*choice) for choice in choices),
            default,
        )
    print()
    for value, name, description in choices:
        suffix = f" - {description}" if description else ""
        print(f"  {value}. {name}{suffix}")
    answer = input(f"{label} [{default}]: ").strip()
    return answer or default


def _setup_confirm(label: str, *, default: bool) -> bool:
    from nous_runtime.cli.screen_wizard import active_wizard

    wizard = active_wizard()
    if wizard is not None:
        return wizard.ask_confirm(label, default=default)
    default_label = "Y/n" if default else "y/N"
    answer = input(f"{label} [{default_label}]: ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes"}


# Save / load config

def save_setup_config(config: SetupConfig, path: str | Path) -> None:
    """Persist setup configuration to JSON."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Strip secrets before saving
    safe = {
        "runtime_mode": config.runtime_mode,
        "install_path": config.install_path,
        "selected_models": config.selected_models,
        "auto_start": config.auto_start,
        "send_telemetry": config.send_telemetry,
        "create_desktop_shortcut": config.create_desktop_shortcut,
        "accepted_license": config.accepted_license,
        "providers": [
            {
                "provider_id": p["provider_id"],
                "credential_ref": str(p.get("credential_ref") or ""),
            }
            for p in config.providers
        ],
    }
    out.write_text(json.dumps(safe, indent=2), encoding="utf-8")


def load_setup_config(path: str | Path) -> SetupConfig | None:
    """Load a saved setup configuration."""
    p = Path(path)
    if not p.is_file():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    config = SetupConfig()
    config.runtime_mode = data.get("runtime_mode", "hybrid")
    config.install_path = data.get("install_path", "")
    config.auto_start = data.get("auto_start", True)
    config.send_telemetry = data.get("send_telemetry", False)
    config.create_desktop_shortcut = data.get("create_desktop_shortcut", True)
    config.accepted_license = data.get("accepted_license", False)
    return config


# CLI integration

def run_setup_cli() -> int:
    """Entry point: `nous setup`"""
    wizard = ConsoleSetupWizard()
    config = wizard.run()
    save_setup_config(
        config,
        Path(config.install_path) / "setup_config.json",
    )
    return 0


__all__ = [
    "HardwareInfo",
    "SetupConfig",
    "detect_hardware",
    "ConsoleSetupWizard",
    "save_setup_config",
    "load_setup_config",
    "run_setup_cli",
]

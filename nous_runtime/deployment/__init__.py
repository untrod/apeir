# -*- coding: utf-8 -*-
"""Deployment System — platform detection, dependency checks, install orchestration."""
from nous_runtime.deployment.installer import DeploymentInstaller
from nous_runtime.deployment.platform_detect import detect_platform
from nous_runtime.deployment.product_installer import (
    InstallMode,
    ProductInstallPlan,
    ProductInstaller,
    SystemProfile,
    detect_system_profile,
)
__all__ = [
    "DeploymentInstaller",
    "InstallMode",
    "ProductInstallPlan",
    "ProductInstaller",
    "SystemProfile",
    "detect_platform",
    "detect_system_profile",
]

# -*- coding: utf-8 -*-
"""Marketplace Security — trust verification and supply chain safety."""

from __future__ import annotations

import logging
from typing import Any

from nous_runtime.ecosystem.manifest import CapabilityManifest
from nous_runtime.network.models import TrustLevel

_log = logging.getLogger("nous.marketplace.security")


class MarketplaceSecurity:
    """Validates capability trust and supply chain safety.

    Trust levels: Official > Verified > Community > Unknown
    """

    TRUST_RANK = {"official": 3, "verified": 2, "community": 1, "unknown": 0}

    @classmethod
    def assess_trust(cls, manifest: CapabilityManifest) -> dict[str, Any]:
        """Assess the trust level of a capability."""
        rank = cls.TRUST_RANK.get(manifest.trust, 0)
        warnings: list[str] = []

        if manifest.trust == TrustLevel.UNKNOWN.value:
            warnings.append("Capability has UNKNOWN trust level — use with caution.")
        if manifest.risk_level in ("high", "critical"):
            warnings.append(f"Capability has {manifest.risk_level.upper()} risk level.")
        if not manifest.signature:
            warnings.append("Capability is not signed — integrity cannot be verified.")
        if manifest.permissions and "network" in manifest.permissions:
            warnings.append("Capability requests network access.")

        return {
            "name": manifest.name,
            "trust_level": manifest.trust,
            "trust_rank": rank,
            "risk_level": manifest.risk_level,
            "signed": bool(manifest.signature),
            "warnings": warnings,
            "safe_to_install": rank >= 1 and manifest.risk_level != "critical",
        }

    @classmethod
    def verify_signature(cls, manifest: CapabilityManifest, public_key: str = "", verifier=None) -> bool:
        """Verify a signature through an explicitly configured cryptographic verifier."""
        if not manifest.signature or not public_key or verifier is None:
            return False
        payload = f"{manifest.name}:{manifest.version}:{manifest.entry_point}".encode()
        try:
            return bool(verifier(payload, manifest.signature, public_key))
        except Exception:
            return False

    @classmethod
    def scan_manifest(cls, manifest: CapabilityManifest) -> list[str]:
        """Scan a manifest for security issues. Returns list of findings."""
        findings: list[str] = []

        if not manifest.name:
            findings.append("Missing name")
        if not manifest.version:
            findings.append("Missing version")
        if not manifest.author:
            findings.append("Missing author — untrusted source")
        if manifest.risk_level == "critical":
            findings.append("CRITICAL risk level — requires manual review")
        if "system" in manifest.permissions:
            findings.append("Requests 'system' permission — high risk")

        # Check for suspicious patterns
        suspicious = ["eval", "exec", "rm -rf", "sudo", "chmod 777"]
        for field in [manifest.description, manifest.entry_point]:
            for pattern in suspicious:
                if pattern in field.lower():
                    findings.append(f"Suspicious pattern '{pattern}' in manifest")

        return findings

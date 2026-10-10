"""Report real prerequisites for the existing thermal report chain; never execute."""

from __future__ import annotations

import json
import platform

from nous_runtime.environments.providers import LocalSandboxProvider
from nous_runtime.scientific.providers import provider_inventory

REQUIRED_PROVIDERS = ("numpy", "scipy", "pandas", "sympy", "matplotlib")


def preflight() -> dict:
    blockers = []
    try:
        isolation = LocalSandboxProvider().probe()
        providers = provider_inventory()
    except Exception as exc:
        isolation, providers = {}, {}
        blockers.append(f"Existing prerequisite probe failed: {type(exc).__name__}")
    if not (
        isolation.get("available") is True
        and isolation.get("hard_network_isolation") is True
        and isolation.get("filesystem_namespace_isolation") is True
        and isolation.get("evidence_level") == "strong-vm"
    ):
        blockers.append(
            "The existing local-sandbox scientific path requires a ready strong Windows Sandbox backend; ordinary host fallback is prohibited."
        )
    blockers.extend(
        f"Required numerical provider unavailable or version unknown: {name}"
        for name in REQUIRED_PROVIDERS
        if providers.get(name, {}).get("available") is not True
        or not isinstance(providers.get(name, {}).get("version"), str)
        or providers[name]["version"].strip() in {"", "unknown"}
    )
    return {
        "status": "BLOCKED" if blockers else "READY_FOR_GOVERNED_RUN",
        "platform": platform.system(),
        "analysis_type": "spacecraft-thermal-analysis/v1",
        "execution_performed": False,
        "reports_created": [],
        "isolation": isolation,
        "providers": providers,
        "blockers": blockers,
        "reference": {"solver": "scipy.solve_ivp:DOP853", "tolerance_kelvin": 0.05},
        "claim_scope": "Numerical comparison and symbolic expressions; not a formal proof or mathematical theorem.",
    }


def main() -> int:
    result = preflight()
    print(json.dumps(result, indent=2))
    return 2 if result["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Qualified scientific providers and the P20 thermal reference analysis."""

from __future__ import annotations

import csv
import importlib.metadata
import json
from pathlib import Path
from typing import Any, Mapping

_PROVIDER_ERRORS: dict[str, str] = {}

try:
    import numpy as np
except Exception as exc:  # pragma: no cover - exercised in frozen acceptance
    np = None
    _PROVIDER_ERRORS["numpy"] = str(exc)

try:
    import pandas as pd
except Exception as exc:  # pragma: no cover - exercised in frozen acceptance
    pd = None
    _PROVIDER_ERRORS["pandas"] = str(exc)

try:
    import scipy
    from scipy.integrate import solve_ivp
except Exception as exc:  # pragma: no cover - exercised in frozen acceptance
    scipy = None
    solve_ivp = None
    _PROVIDER_ERRORS["scipy"] = str(exc)

try:
    import sympy as sp
except Exception as exc:  # pragma: no cover - exercised in frozen acceptance
    sp = None
    _PROVIDER_ERRORS["sympy"] = str(exc)

try:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
except Exception as exc:  # pragma: no cover - exercised in frozen acceptance
    matplotlib = None
    plt = None
    _PROVIDER_ERRORS["matplotlib"] = str(exc)

SIGMA = 5.670374419e-8
_PROVIDER_CAPABILITIES = {
    "numpy": ["array", "statistics", "error-metrics"],
    "scipy": ["ode-reference", "numerical-validation"],
    "pandas": ["dataset-inspection", "tabular-analysis", "csv"],
    "sympy": ["symbolic-equation", "radiative-equilibrium"],
    "matplotlib": ["png-visualization", "comparison-plot"],
}


class ScientificProviderError(RuntimeError):
    """A required scientific provider is unavailable or failed."""


def _module_version(name: str, module: Any) -> str:
    version = str(getattr(module, "__version__", "") or "")
    if version:
        return version
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def provider_inventory() -> dict[str, dict[str, Any]]:
    modules = {
        "numpy": np,
        "scipy": scipy,
        "pandas": pd,
        "sympy": sp,
        "matplotlib": matplotlib,
    }
    return {
        name: {
            "available": module is not None,
            "version": _module_version(name, module) if module is not None else "",
            "capabilities": list(_PROVIDER_CAPABILITIES[name]),
            "error": _PROVIDER_ERRORS.get(name, "")[:512],
        }
        for name, module in modules.items()
    }


def require_providers() -> dict[str, dict[str, Any]]:
    inventory = provider_inventory()
    missing = sorted(name for name, item in inventory.items() if not item["available"])
    if missing:
        raise ScientificProviderError(
            f"required scientific providers are unavailable: {missing}"
        )
    return inventory


def analyze_spacecraft_thermal(
    payload: Mapping[str, Any],
    result_path: Path,
    series_path: Path,
    summary_csv: Path,
    plot_path: Path,
) -> dict[str, Any]:
    """Validate a P19 result with an independent SciPy reference solution."""
    inventory = require_providers()
    if str(payload.get("analysis_type")) != "spacecraft-thermal-analysis/v1":
        raise ScientificProviderError("unsupported analysis_type")
    simulation = payload.get("simulation")
    if not isinstance(simulation, Mapping):
        raise ScientificProviderError("simulation contract is required")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("schema_version") != "nous.simulation-worker-result/v1":
        raise ScientificProviderError("unsupported Simulation worker result")
    if result.get("simulation_id") != simulation.get("simulation_id"):
        raise ScientificProviderError("Simulation result identity mismatch")

    frame = pd.read_csv(series_path)
    required_columns = {"case_id", "time", "temperature"}
    if set(frame.columns) != required_columns:
        raise ScientificProviderError(
            "series.csv must contain case_id,time,temperature"
        )
    if frame.empty or frame.isnull().any().any():
        raise ScientificProviderError("series.csv is empty or contains null values")

    initial_temperature = float(
        (simulation.get("initial_state") or {}).get("initial_temperature")
    )
    external_temperature = float(
        (simulation.get("boundary_conditions") or {}).get("external_temperature")
    )
    tolerance = float(payload.get("reference_tolerance_kelvin") or 0.05)
    result_cases = {
        int(item["case_id"]): item for item in list(result.get("cases") or [])
    }
    analyses: list[dict[str, Any]] = []

    symbol_t = sp.Symbol("T", positive=True)
    symbol_q = sp.Symbol("q_abs", nonnegative=True)
    symbol_eps = sp.Symbol("epsilon", positive=True)
    symbol_area = sp.Symbol("A", positive=True)
    symbol_external = sp.Symbol("T_ext", positive=True)
    equilibrium_expression = (
        symbol_external**4 + symbol_q / (symbol_eps * sp.Float(SIGMA) * symbol_area)
    ) ** sp.Rational(1, 4)
    equation = sp.Eq(
        sp.Symbol("C") * sp.Derivative(symbol_t, sp.Symbol("t")),
        symbol_q
        - symbol_eps
        * sp.Float(SIGMA)
        * symbol_area
        * (symbol_t**4 - symbol_external**4),
    )

    figure, axis = plt.subplots(figsize=(9, 4.8), dpi=120)
    for raw_case_id, group in frame.groupby("case_id", sort=True):
        case_id = int(raw_case_id)
        case = result_cases.get(case_id)
        if case is None:
            raise ScientificProviderError(f"series contains unknown case_id: {case_id}")
        times = group["time"].to_numpy(dtype=float)
        temperatures = group["temperature"].to_numpy(dtype=float)
        if (
            len(times) < 2
            or not np.all(np.isfinite(times))
            or not np.all(np.isfinite(temperatures))
            or not np.all(np.diff(times) > 0)
        ):
            raise ScientificProviderError("series values are not finite and monotonic")
        parameters = dict(case.get("parameters") or {})
        solar_flux = float(parameters["solar_flux"])
        surface_area = float(parameters["surface_area"])
        absorptivity = float(parameters.get("absorptivity", 0.7))
        emissivity = float(parameters["emissivity"])
        thermal_capacity = float(parameters["thermal_capacity"])
        max_safe = float(parameters.get("max_safe_temperature", 373.15))
        absorbed = solar_flux * surface_area * absorptivity

        equilibrium = float(
            sp.N(
                equilibrium_expression.subs(
                    {
                        symbol_external: external_temperature,
                        symbol_q: absorbed,
                        symbol_eps: emissivity,
                        symbol_area: surface_area,
                    }
                ),
                17,
            )
        )

        def thermal_rhs(_time: float, value: Any) -> list[float]:
            temperature = float(value[0])
            radiated = (
                emissivity
                * SIGMA
                * surface_area
                * (temperature**4 - external_temperature**4)
            )
            return [(absorbed - radiated) / thermal_capacity]

        reference = solve_ivp(
            thermal_rhs,
            (float(times[0]), float(times[-1])),
            [initial_temperature],
            t_eval=times,
            method="DOP853",
            rtol=1.0e-11,
            atol=1.0e-12,
        )
        if not reference.success or reference.y.shape[1] != len(times):
            raise ScientificProviderError("SciPy reference integration failed")
        reference_temperature = np.asarray(reference.y[0], dtype=float)
        errors = np.abs(temperatures - reference_temperature)
        metrics = dict(case.get("metrics") or {})
        peak = float(np.max(temperatures))
        final = float(temperatures[-1])
        safety_margin = max_safe - peak
        maximum_error = float(np.max(errors))
        rmse = float(np.sqrt(np.mean(np.square(errors))))
        within = maximum_error <= tolerance
        analyses.append(
            {
                "case_id": case_id,
                "parameters": parameters,
                "sample_count": int(len(times)),
                "peak_temperature_kelvin": peak,
                "final_temperature_kelvin": final,
                "mean_temperature_kelvin": float(np.mean(temperatures)),
                "standard_deviation_kelvin": float(np.std(temperatures)),
                "radiative_equilibrium_kelvin": equilibrium,
                "safety_limit_kelvin": max_safe,
                "mission_safety_margin_kelvin": safety_margin,
                "safe_during_simulated_duration": safety_margin >= 0.0,
                "reference_final_temperature_kelvin": float(reference_temperature[-1]),
                "maximum_reference_error_kelvin": maximum_error,
                "reference_rmse_kelvin": rmse,
                "within_reference_tolerance": within,
                "runtime_metric_consistent": (
                    abs(float(metrics.get("peak_temperature", peak)) - peak) <= 1.0e-9
                    and abs(float(metrics.get("final_temperature", final)) - final)
                    <= 1.0e-9
                ),
            }
        )
        axis.plot(times, temperatures, label=f"Case {case_id} Euler")
        axis.plot(
            times,
            reference_temperature,
            linestyle="--",
            linewidth=1.2,
            label=f"Case {case_id} SciPy",
        )
    for safe_limit in sorted({float(item["safety_limit_kelvin"]) for item in analyses}):
        axis.axhline(
            safe_limit,
            color="#dc2626",
            linewidth=1.0,
            linestyle=":",
            label=f"Safety limit {safe_limit:.2f} K",
        )
    axis.set_title("Spacecraft thermal analysis: Simulation vs SciPy reference")
    axis.set_xlabel("Time (s)")
    axis.set_ylabel("Temperature (K)")
    axis.grid(True, alpha=0.25)
    axis.legend(fontsize=7, ncol=2)
    figure.tight_layout()
    plot_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        plot_path,
        format="png",
        dpi=120,
        metadata={"Software": "Nous Scientific Runtime"},
    )
    plt.close(figure)

    summary_csv.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "case_id",
        "solar_flux",
        "peak_temperature_kelvin",
        "final_temperature_kelvin",
        "radiative_equilibrium_kelvin",
        "mission_safety_margin_kelvin",
        "maximum_reference_error_kelvin",
        "reference_rmse_kelvin",
        "within_reference_tolerance",
        "safe_during_simulated_duration",
    ]
    with summary_csv.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for item in analyses:
            writer.writerow(
                {
                    "case_id": item["case_id"],
                    "solar_flux": item["parameters"].get("solar_flux"),
                    "peak_temperature_kelvin": item["peak_temperature_kelvin"],
                    "final_temperature_kelvin": item["final_temperature_kelvin"],
                    "radiative_equilibrium_kelvin": item[
                        "radiative_equilibrium_kelvin"
                    ],
                    "mission_safety_margin_kelvin": item[
                        "mission_safety_margin_kelvin"
                    ],
                    "maximum_reference_error_kelvin": item[
                        "maximum_reference_error_kelvin"
                    ],
                    "reference_rmse_kelvin": item["reference_rmse_kelvin"],
                    "within_reference_tolerance": item["within_reference_tolerance"],
                    "safe_during_simulated_duration": item[
                        "safe_during_simulated_duration"
                    ],
                }
            )

    return {
        "schema_version": "nous.scientific-worker-result/v1",
        "analysis_id": str(payload.get("analysis_id") or ""),
        "analysis_type": str(payload.get("analysis_type") or ""),
        "simulation_id": str(simulation.get("simulation_id") or ""),
        "simulation_run_id": str(payload.get("simulation_run_id") or ""),
        "reference_solver": "scipy.solve_ivp:DOP853",
        "reference_tolerance_kelvin": tolerance,
        "reference_verified": all(
            item["within_reference_tolerance"] and item["runtime_metric_consistent"]
            for item in analyses
        ),
        "safe_during_simulated_duration": all(
            item["safe_during_simulated_duration"] for item in analyses
        ),
        "equation": str(equation),
        "equilibrium_expression": str(equilibrium_expression),
        "provider_inventory": inventory,
        "case_count": len(analyses),
        "cases": analyses,
    }


__all__ = [
    "ScientificProviderError",
    "analyze_spacecraft_thermal",
    "provider_inventory",
    "require_providers",
]

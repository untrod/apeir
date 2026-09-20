"""Deterministic built-in Simulation worker executed only inside an Environment."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import platform
import random
import sys
from pathlib import Path
from typing import Any, Mapping

from nous_runtime.simulations.models import SimulationSpec, SimulationValidationError

SIGMA = 5.670374419e-8
MODEL_VERSION = "spacecraft-thermal-ode/v1"


class SimulationCancelled(RuntimeError):
    pass


def _below(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def _required(
    values: Mapping[str, float], name: str, minimum: float, maximum: float
) -> float:
    if name not in values:
        raise SimulationValidationError(f"spacecraft thermal model requires {name}")
    value = float(values[name])
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise SimulationValidationError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return value


def _thermal_case(
    spec: SimulationSpec,
    case_id: int,
    parameters: Mapping[str, float],
    cancel: Path | None,
) -> dict[str, Any]:
    initial_temperature = _required(
        spec.initial_state, "initial_temperature", 1.0, 5000.0
    )
    external_temperature = _required(
        spec.boundary_conditions, "external_temperature", 1.0, 5000.0
    )
    solar_flux = _required(parameters, "solar_flux", 0.0, 1.0e7)
    surface_area = _required(parameters, "surface_area", 1.0e-9, 1.0e9)
    emissivity = _required(parameters, "emissivity", 0.0, 1.0)
    thermal_capacity = _required(parameters, "thermal_capacity", 1.0e-9, 1.0e15)
    absorptivity = float(parameters.get("absorptivity", 0.7))
    max_safe_temperature = float(parameters.get("max_safe_temperature", 373.15))
    if not 0.0 <= absorptivity <= 1.0:
        raise SimulationValidationError("absorptivity must be between 0 and 1")
    if not 1.0 <= max_safe_temperature <= 5000.0:
        raise SimulationValidationError(
            "max_safe_temperature must be between 1 and 5000"
        )
    steps = int(math.ceil(spec.duration / spec.time_step))
    if steps < 1 or steps > 100_000:
        raise SimulationValidationError(
            "simulation step count must be between 1 and 100000"
        )
    random.seed(spec.seed + case_id)
    temperature = initial_temperature
    series = [{"time": 0.0, "temperature": temperature}]
    peak = temperature
    last_rate = 0.0
    for index in range(1, steps + 1):
        if cancel is not None and cancel.exists():
            raise SimulationCancelled("simulation cancellation requested")
        absorbed = solar_flux * surface_area * absorptivity
        radiated = (
            emissivity
            * SIGMA
            * surface_area
            * (temperature**4 - external_temperature**4)
        )
        last_rate = (absorbed - radiated) / thermal_capacity
        step = min(spec.time_step, spec.duration - (index - 1) * spec.time_step)
        temperature += step * last_rate
        if not math.isfinite(temperature) or not 0.0 < temperature <= 100_000.0:
            raise SimulationValidationError("solver produced an invalid temperature")
        peak = max(peak, temperature)
        series.append(
            {
                "time": round(min(index * spec.time_step, spec.duration), 12),
                "temperature": round(temperature, 12),
            }
        )
    metrics = {
        "peak_temperature": peak,
        "equilibrium_temperature": temperature,
        "final_temperature": temperature,
        "safety_margin": max_safe_temperature - peak,
        "sample_count": len(series),
    }
    return {
        "case_id": case_id,
        "parameters": dict(parameters),
        "metrics": {key: metrics[key] for key in spec.metric_schema},
        "last_temperature_rate": last_rate,
        "series": series,
    }


def _svg(cases: list[dict[str, Any]], width: int = 900, height: int = 420) -> str:
    points = [point for case in cases for point in case["series"]]
    min_t = min(point["time"] for point in points)
    max_t = max(point["time"] for point in points)
    min_y = min(point["temperature"] for point in points)
    max_y = max(point["temperature"] for point in points)
    span_t = max(max_t - min_t, 1.0)
    span_y = max(max_y - min_y, 1.0)
    colors = ("#2563eb", "#dc2626", "#059669", "#7c3aed", "#d97706", "#0891b2")
    lines: list[str] = []
    for index, case in enumerate(cases):
        coords = []
        for point in case["series"]:
            x = 60 + (point["time"] - min_t) / span_t * (width - 90)
            y = 25 + (max_y - point["temperature"]) / span_y * (height - 70)
            coords.append(f"{x:.2f},{y:.2f}")
        lines.append(
            f'<polyline fill="none" stroke="{colors[index % len(colors)]}" '
            f'stroke-width="2" points="{" ".join(coords)}"/>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="white"/>'
        f'<text x="24" y="20" font-family="sans-serif" font-size="14">Spacecraft thermal simulation</text>'
        f'<line x1="60" y1="{height - 45}" x2="{width - 30}" y2="{height - 45}" stroke="#64748b"/>'
        f'<line x1="60" y1="25" x2="60" y2="{height - 45}" stroke="#64748b"/>'
        + "".join(lines)
        + "</svg>\n"
    )


def execute_payload(
    payload: Mapping[str, Any], output_dir: Path, cancel_file: Path | None = None
) -> dict[str, Any]:
    spec = SimulationSpec.from_mapping(payload)
    if spec.model_ref != "spacecraft-thermal/v1":
        raise SimulationValidationError("unsupported built-in model_ref")
    output_dir.mkdir(parents=True, exist_ok=True)
    cases = [
        _thermal_case(spec, index, parameters, cancel_file)
        for index, parameters in enumerate(spec.cases())
    ]
    summary = {
        "schema_version": "nous.simulation-worker-result/v1",
        "simulation_id": spec.simulation_id,
        "model_ref": spec.model_ref,
        "model_version": MODEL_VERSION,
        "solver": spec.solver,
        "time_step": spec.time_step,
        "duration": spec.duration,
        "seed": spec.seed,
        "case_count": len(cases),
        "cases": [
            {
                "case_id": item["case_id"],
                "parameters": item["parameters"],
                "metrics": item["metrics"],
                "last_temperature_rate": item["last_temperature_rate"],
            }
            for item in cases
        ],
        "dependency_versions": {
            "python": platform.python_version(),
            "numpy": _version("numpy"),
            "scipy": _version("scipy"),
            "pandas": _version("pandas"),
            "sympy": _version("sympy"),
            "matplotlib": _version("matplotlib"),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
        },
    }
    canonical = json.dumps(
        summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    summary["result_digest"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    (output_dir / "result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if "csv" in spec.output_schema:
        with (output_dir / "series.csv").open(
            "w", encoding="utf-8", newline=""
        ) as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["case_id", "time", "temperature"])
            for case in cases:
                for point in case["series"]:
                    writer.writerow(
                        [case["case_id"], point["time"], point["temperature"]]
                    )
    if "svg" in spec.output_schema:
        (output_dir / "temperature.svg").write_text(_svg(cases), encoding="utf-8")
    return summary


def _version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nous simulation-worker")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--cancel-file", default="")
    args = parser.parse_args(argv)
    root = Path.cwd().resolve()
    source = (root / args.input).resolve()
    output = (root / args.output_dir).resolve()
    cancel = (root / args.cancel_file).resolve() if args.cancel_file else None
    if (
        not _below(root, source)
        or not _below(root, output)
        or (cancel and not _below(root, cancel))
    ):
        print(
            json.dumps({"ok": False, "error": "worker path escaped environment"}),
            file=sys.stderr,
        )
        return 2
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        result = execute_payload(payload, output, cancel)
    except SimulationCancelled as exc:
        print(
            json.dumps({"ok": False, "cancelled": True, "error": str(exc)}),
            file=sys.stderr,
        )
        return 130
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "ok": True,
                "simulation_id": result["simulation_id"],
                "result_digest": result["result_digest"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Internal P20 scientific worker executed inside an Environment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from nous_runtime.scientific.providers import analyze_spacecraft_thermal


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nous scientific-worker")
    parser.add_argument("--input", required=True)
    parser.add_argument("--simulation-result", required=True)
    parser.add_argument("--series", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    input_path = Path(args.input).resolve()
    result_path = Path(args.simulation_result).resolve()
    series_path = Path(args.series).resolve()
    output_dir = Path(args.output_dir).resolve()
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    analysis = analyze_spacecraft_thermal(
        payload,
        result_path,
        series_path,
        output_dir / "thermal-analysis.csv",
        output_dir / "thermal-analysis.png",
    )
    (output_dir / "analysis.json").write_text(
        json.dumps(analysis, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]

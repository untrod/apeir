# -*- coding: utf-8 -*-
"""Nous Execution Benchmark — v1.0.0-rc1

Public, versioned, reproducible benchmark for Runtime intelligence evaluation.
20 task types, 14 baselines, automated runner with metrics collection.

Usage:
    python benchmarks/runner.py --task-type code_audit --baseline fixed_strongest
    python benchmarks/runner.py --all --output .audit/benchmark-results.json
"""

from .runner import BenchmarkRunner, BenchmarkResult, run_benchmark

__all__ = ["BenchmarkRunner", "BenchmarkResult", "run_benchmark"]

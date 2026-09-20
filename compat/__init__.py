"""
compat — Compatibility FACADE between the existing Nous Runtime (Python)
and the new Nous AI Kernel (Rust, via NKI).

IMPORTANT: This is NOT a second authoritative path. It is a FACADE that
translates old API calls to NKI requests. All state authority resides in
nousd (the Rust kernel). This module does NOT maintain parallel state,
bypass governance, or call providers directly.

This package provides:
- nki_client: Python NKI client for communicating with nousd
- CompatibilityFacade: Translates old RuntimeRequest/Response to NKI WorkloadSpec
- Migration utilities: Data migration from old stores to new journal

During the migration period, this package is how the existing
CLI, HTTP API, desktop, and SDK interact with the new kernel.
"""

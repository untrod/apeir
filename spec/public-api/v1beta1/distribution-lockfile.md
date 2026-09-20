# Nous Distribution Lockfile — v1beta1

> Version: 1.0.0-beta1
> Status: v1beta1

## Purpose

A reproducible, hash-pinned description of every component in a Nous Distribution.
Equivalent to `package-lock.json` / `Cargo.lock` — enables deterministic builds
and security audits.

## Schema

```json
{
  "schema_version": "1.0.0-beta1",
  "distribution": {
    "name": "nous-core-reference",
    "version": "2.0.0-rc7",
    "vendor": "Nous AI Foundation",
    "platform": "linux-x86_64",
    "created_at": "2026-08-05T00:00:00Z"
  },
  "kernel": {
    "name": "nous-kernel",
    "version": "2.0.0-rc7",
    "digest": "sha256:abcdef...",
    "source": "oci://registry.nous.ai/nous/kernel",
    "signature": "sha256:sig..."
  },
  "runtime": {
    "name": "nous-runtime",
    "version": "2.0.0-rc7",
    "digest": "sha256:...",
    "source": "oci://registry.nous.ai/nous/runtime"
  },
  "providers": [
    {
      "name": "nous-provider-cpu",
      "version": "1.0.0",
      "digest": "sha256:...",
      "source": "oci://registry.nous.ai/nous/providers/cpu",
      "conformance": "CERTIFIED",
      "required": true
    },
    {
      "name": "nous-provider-nvidia",
      "version": "1.0.0",
      "digest": "sha256:...",
      "source": "oci://registry.nous.ai/nvidia/provider",
      "conformance": "CERTIFIED",
      "required": false,
      "hardware": ["nvidia.cuda"],
      "driver_min": "535.0"
    }
  ],
  "engines": [
    {
      "name": "llama.cpp",
      "version": "b4567",
      "digest": "sha256:...",
      "source": "oci://registry.nous.ai/nous/engines/llama.cpp",
      "platforms": ["cpu", "cuda", "metal"]
    },
    {
      "name": "vllm",
      "version": "0.8.0",
      "digest": "sha256:...",
      "source": "oci://registry.nous.ai/nous/engines/vllm",
      "platforms": ["cuda", "rocm"]
    }
  ],
  "models": [
    {
      "name": "Qwen2.5-7B-Instruct",
      "version": "1.0.0",
      "digest": "sha256:...",
      "source": "oci://registry.nous.ai/models/Qwen2.5-7B-Instruct",
      "profiles": ["gguf-q4", "gguf-q8", "onnx-fp16"]
    }
  ],
  "policies": {
    "scheduler": {
      "name": "weighted-sum",
      "config": {
        "weights": {
          "latency": 0.3,
          "cost": 0.2,
          "quality": 0.3,
          "cache_hit": 0.2
        }
      }
    },
    "governance": {
      "name": "standard",
      "config": {
        "auto_approve_risk": "low",
        "require_approval_risk": "high",
        "fail_closed": true
      }
    },
    "security": {
      "baseline": "standard",
      "config": {
        "allow_anonymous_readonly": true,
        "isolation_default": "strict"
      }
    }
  },
  "security": {
    "sbom": {
      "digest": "sha256:...",
      "format": "spdx",
      "source": "oci://registry.nous.ai/nous/distributions/core/sbom"
    },
    "provenance": {
      "digest": "sha256:...",
      "format": "slsa",
      "level": "SLSA_LEVEL_3"
    },
    "signatures": {
      "root": "sha256:...",
      "timestamp": "sha256:...",
      "snapshot": "sha256:...",
      "targets": "sha256:..."
    }
  }
}
```

## Lockfile Commands

```
nous distro resolve   — Resolve all dependencies and update lockfile
nous distro lock      — Generate a hash-pinned lockfile
nous distro verify    — Verify all digests in the lockfile
nous distro diff      — Show changes from previous lockfile
```

## Reproducibility

- All artifacts referenced by digest (sha256), not by tag (mutable)
- Lockfile is checked into version control
- `nous distro build` reads the lockfile and reproduces exactly
- Any digest mismatch is a build error

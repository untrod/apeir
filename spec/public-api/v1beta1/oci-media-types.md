# Nous OCI Artifact Media Types — v1beta1

> Version: 1.0.0-beta1
> Status: v1beta1
> Reference: OCI Image and Distribution Spec v1.1

## Design

Nous uses OCI Artifacts for all distributable software and model packages.
This provides: content-addressable storage, signing, SBOM attachment via
Referrers API, and interoperability with existing container registries.

## Media Types

### Model Artifacts

| Media Type | Description |
|-----------|-------------|
| `application/vnd.nous.model.manifest.v1+json` | Model package manifest |
| `application/vnd.nous.model.weights.v1.tar+gzip` | Model weights (generic) |
| `application/vnd.nous.model.weights.gguf.v1` | GGUF format weights |
| `application/vnd.nous.model.weights.safetensors.v1` | SafeTensors weights |
| `application/vnd.nous.model.weights.onnx.v1` | ONNX model |
| `application/vnd.nous.model.tokenizer.v1.tar+gzip` | Tokenizer files |
| `application/vnd.nous.model.chat-template.v1+json` | Chat template |
| `application/vnd.nous.model.engine-profile.v1+json` | Per-engine profile (quantization, KV config, benchmarks) |
| `application/vnd.nous.model.benchmark.v1+json` | Benchmark results |

### Provider Artifacts

| Media Type | Description |
|-----------|-------------|
| `application/vnd.nous.provider.manifest.v1+json` | Provider package manifest |
| `application/vnd.nous.provider.bundle.v1.tar+gzip` | Provider bundle (code + config) |
| `application/vnd.nous.provider.conformance.v1+json` | Conformance test results |

### Engine Artifacts

| Media Type | Description |
|-----------|-------------|
| `application/vnd.nous.engine.manifest.v1+json` | Engine adapter manifest |
| `application/vnd.nous.engine.bundle.v1.tar+gzip` | Engine adapter bundle |

### Distribution Artifacts

| Media Type | Description |
|-----------|-------------|
| `application/vnd.nous.distribution.manifest.v1+json` | Distribution manifest |
| `application/vnd.nous.distribution.lockfile.v1+json` | Resolved dependency lockfile |
| `application/vnd.nous.distribution.bundle.v1.tar+gzip` | Full distribution package |

### Security Artifacts (OCI standard + Nous extension)

| Media Type | Description |
|-----------|-------------|
| `application/vnd.nous.sbom.spdx.v1+json` | SPDX SBOM |
| `application/vnd.nous.provenance.slsa.v1+json` | SLSA provenance |
| `application/vnd.nous.signature.v1+json` | Cryptographic signature |

### Policy Artifacts

| Media Type | Description |
|-----------|-------------|
| `application/vnd.nous.policy.scheduler.v1+json` | Scheduler policy definition |
| `application/vnd.nous.policy.governance.v1+json` | Governance policy definition |
| `application/vnd.nous.policy.security.v1+json` | Security baseline definition |

## Referrers API Usage

All artifacts use OCI 1.1 Referrers API to link related objects:

```
Model Manifest
├── subject → (none, it's the root)
├── referrer: SBOM (application/vnd.nous.sbom.spdx.v1+json)
├── referrer: Signature (application/vnd.nous.signature.v1+json)
├── referrer: Provenance (application/vnd.nous.provenance.slsa.v1+json)
├── referrer: Benchmark (application/vnd.nous.model.benchmark.v1+json)
└── referrer: Engine Profiles (application/vnd.nous.model.engine-profile.v1+json)
    ├── profile: NVIDIA-TensorRT
    ├── profile: AMD-ROCm
    ├── profile: Qualcomm-QNN
    └── profile: CPU-ONNX
```

## Model Manifest Schema

```json
{
  "schemaVersion": 1,
  "mediaType": "application/vnd.nous.model.manifest.v1+json",
  "artifactType": "nous.model",
  "annotations": {
    "nous.model.family": "Qwen",
    "nous.model.architecture": "Qwen2.5",
    "nous.model.parameters": "72000000000",
    "nous.model.license": "Apache-2.0",
    "nous.model.source": "https://huggingface.co/Qwen/Qwen2.5-72B"
  },
  "layers": [
    {
      "mediaType": "application/vnd.nous.model.weights.safetensors.v1",
      "digest": "sha256:...",
      "size": 144000000000,
      "annotations": {
        "nous.model.precision": "bf16",
        "nous.model.shard": "1/5"
      }
    }
  ],
  "subject": null
}
```

## Provider Manifest Schema

```json
{
  "schemaVersion": 1,
  "mediaType": "application/vnd.nous.provider.manifest.v1+json",
  "artifactType": "nous.provider",
  "annotations": {
    "nous.provider.name": "nous-provider-nvidia",
    "nous.provider.version": "1.0.0",
    "nous.provider.class": "device",
    "nous.provider.vendor": "NVIDIA",
    "nous.kernel.min": "2.0.0",
    "nous.kernel.max": "2.99.0",
    "nous.provider.os": "linux-x86_64,windows-x86_64",
    "nous.provider.conformance": "CERTIFIED"
  },
  "layers": [
    {
      "mediaType": "application/vnd.nous.provider.bundle.v1.tar+gzip",
      "digest": "sha256:...",
      "size": 5242880,
      "annotations": {
        "nous.provider.driver.min": "535.0",
        "nous.provider.runtime": "CUDA 12.4"
      }
    }
  ]
}
```

## Registry Commands

```
nous registry add <url>                    Add a registry
nous registry list                         List configured registries
nous registry trust <url> [--fingerprint]  Trust a registry
nous provider search <query>               Search for providers
nous provider install <name>               Install a provider
nous provider update <name>                Update a provider
nous provider rollback <name>              Roll back to previous version
nous provider remove <name>                Remove a provider
nous provider verify <name>                Verify signatures and SBOM
nous model search <query>                  Search for models
nous model pull <name>                     Pull a model package
nous model verify <name>                   Verify model integrity
```

## Security

- All artifacts MUST be signed before publication
- `nous provider install` defaults to `--verify=true`
- Unsigned artifacts require explicit `--insecure` flag
- SBOM is mandatory for all published artifacts
- Provenance is mandatory for all official Nous artifacts
- Private registries are supported via OCI credential helpers

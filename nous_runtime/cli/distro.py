"""
Distribution Kit — `nous distro` CLI for building, validating, signing,
and testing Nous distribution packages.

A Nous Distribution bundles:
  - Default Provider set (engines, devices)
  - Default models and policies
  - Scheduler policy configuration
  - Security baseline
  - Platform profiles (edge, server, desktop)
  - Branding and update policy

The Distribution Kit does NOT bundle the Nous Kernel itself — the Kernel
is the common substrate that all distributions target, similar to how
Linux distributions target the Linux kernel.

Package format: .nousp (Nous Provider Package) — OCI-compatible tar
with manifest.json at root.

Commands:
    nous distro init       — Initialize a new distribution project
    nous distro validate   — Validate a distribution package
    nous distro build      — Build a distributable package
    nous distro test       — Run distribution-level conformance tests
    nous distro sign       — Sign a distribution package
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("nous.distro")


# ────────────────────────────────────────────────────────────
# Distribution manifest
# ────────────────────────────────────────────────────────────

@dataclass
class DistributionManifest:
    """Schema for a Nous Distribution package."""

    # Identity
    name: str = ""
    version: str = "0.1.0"
    description: str = ""
    vendor: str = ""
    homepage: str = ""
    license: str = "Apache-2.0"

    # Compatibility
    kernel_version_min: str = "2.0.0"
    kernel_version_max: str = "2.99.0"
    nki_version: int = 2
    platform: str = "any"  # "linux-x86_64", "win32-x86_64", "any"

    # Contents
    providers: list[dict] = field(default_factory=list)
    engines: list[dict] = field(default_factory=list)
    models: list[dict] = field(default_factory=list)
    policies: dict = field(default_factory=dict)

    # Security
    security_baseline: str = "standard"  # "minimal", "standard", "strict"
    isolation_default: str = "strict"
    signing_key_id: str = ""
    sbom_url: str = ""

    # Updates
    update_channel: str = "stable"
    update_url: str = ""

    # Metadata
    created_at: str = ""
    checksum_sha256: str = ""

    def to_dict(self) -> dict:
        return {
            "schema_version": "1.0.0",
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "vendor": self.vendor,
            "homepage": self.homepage,
            "license": self.license,
            "kernel_version_min": self.kernel_version_min,
            "kernel_version_max": self.kernel_version_max,
            "nki_version": self.nki_version,
            "platform": self.platform,
            "providers": self.providers,
            "engines": self.engines,
            "models": self.models,
            "policies": self.policies,
            "security_baseline": self.security_baseline,
            "isolation_default": self.isolation_default,
            "signing_key_id": self.signing_key_id,
            "sbom_url": self.sbom_url,
            "update_channel": self.update_channel,
            "update_url": self.update_url,
            "created_at": self.created_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "checksum_sha256": self.checksum_sha256,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DistributionManifest":
        return cls(
            name=d.get("name", ""),
            version=d.get("version", "0.1.0"),
            description=d.get("description", ""),
            vendor=d.get("vendor", ""),
            homepage=d.get("homepage", ""),
            license=d.get("license", "Apache-2.0"),
            kernel_version_min=d.get("kernel_version_min", "2.0.0"),
            kernel_version_max=d.get("kernel_version_max", "2.99.0"),
            nki_version=int(d.get("nki_version", 2)),
            platform=d.get("platform", "any"),
            providers=d.get("providers", []),
            engines=d.get("engines", []),
            models=d.get("models", []),
            policies=d.get("policies", {}),
            security_baseline=d.get("security_baseline", "standard"),
            isolation_default=d.get("isolation_default", "strict"),
            signing_key_id=d.get("signing_key_id", ""),
            sbom_url=d.get("sbom_url", ""),
            update_channel=d.get("update_channel", "stable"),
            update_url=d.get("update_url", ""),
            created_at=d.get("created_at", ""),
            checksum_sha256=d.get("checksum_sha256", ""),
        )

    def validate(self) -> list[str]:
        """Validate the manifest. Returns list of issues (empty = valid)."""
        issues = []
        if not self.name or not self.name.strip():
            issues.append("name is required")
        if not self.version:
            issues.append("version is required")
        if not self.kernel_version_min:
            issues.append("kernel_version_min is required")
        # Validate providers
        for i, provider in enumerate(self.providers):
            if not provider.get("name"):
                issues.append(f"providers[{i}]: name is required")
            if not provider.get("provider_class"):
                issues.append(f"providers[{i}]: provider_class is required (e.g. 'device', 'engine')")
        return issues


# ────────────────────────────────────────────────────────────
# Distribution Builder
# ────────────────────────────────────────────────────────────

class DistributionBuilder:
    """Build, validate, and sign Nous Distribution packages."""

    # Standard directories in a distribution package
    DIRS = ["providers", "engines", "models", "policies", "profiles", "docs"]

    def __init__(self, project_dir: str | Path):
        self.project_dir = Path(project_dir).resolve()
        self.manifest_path = self.project_dir / "manifest.json"
        self.build_dir = self.project_dir / "build"
        self.dist_dir = self.project_dir / "dist"

    def init(self, name: str, version: str = "0.1.0", *,
             vendor: str = "", platform: str = "any",
             profile: str = "standard") -> Path:
        """Initialize a new distribution project.

        Creates the directory structure and a template manifest.json.
        """
        if self.project_dir.exists() and list(self.project_dir.iterdir()):
            raise FileExistsError(
                f"Project directory is not empty: {self.project_dir}"
            )

        # Create directory structure
        for d in self.DIRS:
            (self.project_dir / d).mkdir(parents=True, exist_ok=True)

        self.build_dir.mkdir(parents=True, exist_ok=True)
        self.dist_dir.mkdir(parents=True, exist_ok=True)

        # Profile-specific defaults
        profiles = {
            "standard": {
                "providers": [
                    {"name": "nous-provider-cpu", "provider_class": "device", "version": "1.0.0"},
                    {"name": "nous-provider-openai", "provider_class": "engine", "version": "1.0.0"},
                ],
                "engines": [
                    {"name": "llama.cpp", "engine_type": "cpu", "version": "latest"},
                    {"name": "onnx-runtime", "engine_type": "cpu", "version": "latest"},
                ],
            },
            "edge": {
                "providers": [
                    {"name": "nous-provider-cpu", "provider_class": "device", "version": "1.0.0"},
                    {"name": "nous-provider-jetson", "provider_class": "device", "version": "1.0.0"},
                ],
                "engines": [
                    {"name": "llama.cpp", "engine_type": "cpu", "version": "latest"},
                    {"name": "executorch", "engine_type": "edge", "version": "latest"},
                ],
            },
            "server": {
                "providers": [
                    {"name": "nous-provider-nvidia", "provider_class": "device", "version": "1.0.0"},
                    {"name": "nous-provider-vllm", "provider_class": "engine", "version": "1.0.0"},
                ],
                "engines": [
                    {"name": "vllm", "engine_type": "cuda", "version": "latest"},
                    {"name": "tensorrt-llm", "engine_type": "cuda", "version": "latest"},
                ],
            },
        }

        profile_config = profiles.get(profile, profiles["standard"])

        manifest = DistributionManifest(
            name=name,
            version=version,
            vendor=vendor,
            platform=platform,
            providers=profile_config["providers"],
            engines=profile_config["engines"],
            policies={
                "scheduler": "weighted-sum",
                "default_priority": "interactive",
                "lease_duration_seconds": 300,
            },
            security_baseline="standard",
            isolation_default="strict",
            update_channel="stable",
        )

        # A generated reference distribution must validate and build without
        # requiring callers to create placeholder component directories.
        for provider in manifest.providers:
            provider_dir = self.project_dir / "providers" / provider["name"]
            provider_dir.mkdir(parents=True, exist_ok=True)
            (provider_dir / "provider.json").write_text(
                json.dumps(provider, indent=2) + "\n",
                encoding="utf-8",
            )
        for engine in manifest.engines:
            engine_dir = self.project_dir / "engines" / engine["name"]
            engine_dir.mkdir(parents=True, exist_ok=True)
            (engine_dir / "engine.json").write_text(
                json.dumps(engine, indent=2) + "\n",
                encoding="utf-8",
            )

        # Write manifest
        self.manifest_path.write_text(
            json.dumps(manifest.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )

        # Write a README
        (self.project_dir / "README.md").write_text(
            f"# {name}\n\n{manifest.description or 'A Nous Distribution.'}\n\n"
            f"## Profile: {profile}\n\n"
            f"- Kernel: {manifest.kernel_version_min}+\n"
            f"- Platform: {platform}\n"
            f"- Providers: {len(manifest.providers)}\n"
            f"- Engines: {len(manifest.engines)}\n",
            encoding="utf-8",
        )

        # Write a .gitignore
        (self.project_dir / ".gitignore").write_text(
            "build/\ndist/\n*.pyc\n__pycache__/\n.nousp\n",
            encoding="utf-8",
        )

        log.info("Initialized distribution project: %s", self.project_dir)
        return self.manifest_path

    def validate(self) -> tuple[bool, list[str]]:
        """Validate a distribution project.

        Returns (is_valid, list_of_issues).
        """
        all_issues = []

        if not self.manifest_path.is_file():
            return False, [f"manifest.json not found at {self.manifest_path}"]

        try:
            manifest_data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return False, [f"Invalid JSON in manifest.json: {exc}"]

        manifest = DistributionManifest.from_dict(manifest_data)
        manifest_issues = manifest.validate()
        all_issues.extend(manifest_issues)

        # Validate version format (semver-like)
        version_parts = manifest.version.split(".")
        if len(version_parts) < 3:
            all_issues.append("version must be semver-like (e.g., 1.0.0)")

        # Validate platform
        valid_platforms = {"any", "linux-x86_64", "linux-arm64", "win32-x86_64",
                           "win32-arm64", "darwin-arm64", "darwin-x86_64"}
        if manifest.platform not in valid_platforms:
            all_issues.append(
                f"platform '{manifest.platform}' is not recognized. "
                f"Valid: {', '.join(sorted(valid_platforms))}"
            )

        # Validate security baseline
        valid_baselines = {"minimal", "standard", "strict"}
        if manifest.security_baseline not in valid_baselines:
            all_issues.append(
                f"security_baseline '{manifest.security_baseline}' not recognized. "
                f"Valid: {', '.join(sorted(valid_baselines))}"
            )

        # Validate that referenced provider/engine files exist
        for i, provider in enumerate(manifest.providers):
            provider_dir = self.project_dir / "providers" / provider.get("name", "")
            if not provider_dir.is_dir():
                all_issues.append(
                    f"providers[{i}]: directory not found: providers/{provider.get('name', 'unknown')}"
                )

        for i, engine in enumerate(manifest.engines):
            engine_dir = self.project_dir / "engines" / engine.get("name", "")
            if not engine_dir.is_dir():
                all_issues.append(
                    f"engines[{i}]: directory not found: engines/{engine.get('name', 'unknown')}"
                )

        is_valid = len(all_issues) == 0
        return is_valid, all_issues

    def build(self) -> Path:
        """Build a distributable .nousp package.

        The package is a tar.gz archive with:
          manifest.json        — Distribution manifest
          providers/           — Provider bundles
          engines/             — Engine configurations
          models/              — Model references/cards
          policies/            — Scheduler and security policies
          profiles/            — Platform profiles
          checksums.json       — SHA-256 checksums of all files
        """
        # Validate first
        is_valid, issues = self.validate()
        if not is_valid:
            raise ValueError(
                "Distribution validation failed:\n  " + "\n  ".join(issues)
            )

        self.build_dir.mkdir(parents=True, exist_ok=True)
        self.dist_dir.mkdir(parents=True, exist_ok=True)

        manifest_data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest = DistributionManifest.from_dict(manifest_data)

        # Collect all files
        file_checksums: dict[str, str] = {}
        package_name = f"{manifest.name}-{manifest.version}"

        # Build a temporary staging directory
        staging = Path(tempfile.mkdtemp(prefix="nous-distro-"))
        try:
            # Copy manifest
            shutil.copy2(self.manifest_path, staging / "manifest.json")
            _checksum_file(staging / "manifest.json", file_checksums)

            # Copy directories
            for dir_name in self.DIRS:
                src_dir = self.project_dir / dir_name
                if src_dir.is_dir() and list(src_dir.iterdir()):
                    dst_dir = staging / dir_name
                    shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)
                    for f in dst_dir.rglob("*"):
                        if f.is_file():
                            rel = str(f.relative_to(staging)).replace("\\", "/")
                            _checksum_file(f, file_checksums, rel)

            # Copy README if exists
            readme = self.project_dir / "README.md"
            if readme.is_file():
                shutil.copy2(readme, staging / "README.md")
                _checksum_file(staging / "README.md", file_checksums)

            # Write checksums
            checksums_path = staging / "checksums.json"
            checksums_path.write_text(
                json.dumps(file_checksums, indent=2) + "\n",
                encoding="utf-8",
            )
            _checksum_file(checksums_path, file_checksums, "checksums.json")

            # Compute final package checksum and write to manifest
            manifest.checksum_sha256 = _sha256_file(self.manifest_path)
            manifest.created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            updated_manifest = staging / "manifest.json"
            updated_manifest.write_text(
                json.dumps(manifest.to_dict(), indent=2) + "\n",
                encoding="utf-8",
            )

            # Create tar.gz
            package_file = self.dist_dir / f"{package_name}.nousp"
            with tarfile.open(package_file, "w:gz") as tar:
                for item in sorted(staging.iterdir()):
                    tar.add(item, arcname=item.name)

        finally:
            shutil.rmtree(staging, ignore_errors=True)

        log.info("Built distribution package: %s", package_file)
        return package_file

    def test(self) -> tuple[bool, str]:
        """Run distribution-level validation tests.

        Returns (passed, report).
        """
        lines = [
            f"Distribution Test Report - {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Project: {self.project_dir}",
            "",
        ]

        # 1. Manifest validation
        is_valid, issues = self.validate()
        lines.append(f"[{'PASS' if is_valid else 'FAIL'}] Manifest validation")
        for issue in issues:
            lines.append(f"  - {issue}")
        lines.append("")

        # 2. Directory structure
        missing_dirs = [d for d in self.DIRS if not (self.project_dir / d).is_dir()]
        structure_ok = len(missing_dirs) == 0
        lines.append(f"[{'PASS' if structure_ok else 'FAIL'}] Directory structure")
        for d in missing_dirs:
            lines.append(f"  - Missing: {d}/")
        lines.append("")

        # 3. Provider verification
        manifest_data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest = DistributionManifest.from_dict(manifest_data)
        provider_ok = True
        for provider in manifest.providers:
            pdir = self.project_dir / "providers" / provider.get("name", "")
            has_manifest = (pdir / "provider.json").is_file()
            if not has_manifest:
                lines.append(f"  - Provider '{provider.get('name')}': missing provider.json")
                provider_ok = False
        lines.append(f"[{'PASS' if provider_ok else 'FAIL'}] Provider manifests")
        lines.append("")

        # 4. Policy validation
        policies = manifest.policies
        policy_ok = True
        valid_schedulers = {"fifo", "priority", "weighted-sum", "multiplicative",
                            "pareto", "cache-aware", "deadline-aware", "contextual-bandit"}
        scheduler = policies.get("scheduler", "")
        if scheduler and scheduler not in valid_schedulers:
            lines.append(f"  - Unknown scheduler policy: {scheduler}")
            policy_ok = False
        lines.append(f"[{'PASS' if policy_ok else 'FAIL'}] Policy configuration")
        lines.append("")

        all_passed = is_valid and structure_ok and provider_ok and policy_ok
        return all_passed, "\n".join(lines)

    def sign(self, key_path: str | None = None) -> Path:
        """Sign a distribution package (placeholder — real signing TBD).

        For production: uses ed25519 or RSA key to sign the checksums.json.
        For now: computes and embeds SHA-256 checksums.
        """
        if not self.dist_dir.exists():
            raise FileNotFoundError("No packages built. Run 'nous distro build' first.")

        packages = sorted(self.dist_dir.glob("*.nousp"))
        if not packages:
            raise FileNotFoundError("No .nousp packages found in dist/")

        pkg = packages[-1]  # Sign the latest
        manifest = DistributionManifest.from_dict(
            json.loads(self.manifest_path.read_text(encoding="utf-8"))
        )

        # Compute signature (placeholder: SHA-256)
        pkg_hash = _sha256_file(pkg)
        sig_path = pkg.with_suffix(".nousp.sig")
        sig_data = {
            "package": str(pkg.name),
            "sha256": pkg_hash,
            "algorithm": "SHA-256",
            "signed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "signer": manifest.vendor or "unknown",
            "key_id": manifest.signing_key_id or "unsigned",
        }
        sig_path.write_text(json.dumps(sig_data, indent=2) + "\n", encoding="utf-8")

        log.info("Signed package: %s → %s", pkg, sig_path)
        return sig_path


# ────────────────────────────────────────────────────────────
# Reference distributions
# ────────────────────────────────────────────────────────────

REFERENCE_DISTRIBUTIONS = {
    "nous-core-reference": {
        "name": "nous-core-reference",
        "version": "2.0.0-rc6",
        "description": "Nous Core Reference Distribution — general-purpose AI runtime",
        "profile": "standard",
        "platform": "any",
    },
    "nous-edge-reference": {
        "name": "nous-edge-reference",
        "version": "2.0.0-rc6",
        "description": "Nous Edge Reference Profile — Jetson, ARM64, mobile NPU",
        "profile": "edge",
        "platform": "linux-arm64",
    },
    "nous-server-reference": {
        "name": "nous-server-reference",
        "version": "2.0.0-rc6",
        "description": "Nous Server Reference Profile — multi-GPU, high-throughput",
        "profile": "server",
        "platform": "linux-x86_64",
    },
}


def init_reference_distribution(name: str, target_dir: str | Path) -> Path:
    """Initialize one of the reference distributions."""
    ref = REFERENCE_DISTRIBUTIONS.get(name)
    if not ref:
        available = ", ".join(REFERENCE_DISTRIBUTIONS.keys())
        raise ValueError(f"Unknown reference distribution: {name}. Available: {available}")

    builder = DistributionBuilder(target_dir)
    return builder.init(
        name=ref["name"],
        version=ref["version"],
        vendor="Nous AI Foundation",
        platform=ref["platform"],
        profile=ref["profile"],
    )


# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────

def _sha256_file(path: Path) -> str:
    """Compute SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _checksum_file(path: Path, checksums: dict[str, str], rel: str | None = None) -> None:
    """Add a file's checksum to the checksums dict."""
    key = rel or path.name
    checksums[key] = _sha256_file(path)


# ────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    """CLI entry point for `nous distro`."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="nous distro",
        description="Nous Distribution Kit - build and manage distribution packages",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = sub.add_parser("init", help="Initialize a new distribution project")
    p_init.add_argument("name", help="Distribution name (e.g., my-nous-distro)")
    p_init.add_argument("--version", default="0.1.0", help="Version (default: 0.1.0)")
    p_init.add_argument("--vendor", default="", help="Vendor name")
    p_init.add_argument("--platform", default="any", help="Target platform")
    p_init.add_argument("--profile", default="standard",
                        choices=["standard", "edge", "server"],
                        help="Reference profile")
    p_init.add_argument("--dir", default=".", help="Project directory")

    # validate
    p_val = sub.add_parser("validate", help="Validate a distribution project")
    p_val.add_argument("--dir", default=".", help="Project directory")

    # build
    p_build = sub.add_parser("build", help="Build a .nousp package")
    p_build.add_argument("--dir", default=".", help="Project directory")

    # test
    p_test = sub.add_parser("test", help="Run distribution-level tests")
    p_test.add_argument("--dir", default=".", help="Project directory")

    # sign
    p_sign = sub.add_parser("sign", help="Sign a distribution package")
    p_sign.add_argument("--dir", default=".", help="Project directory")
    p_sign.add_argument("--key", default=None, help="Signing key path")

    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            builder = DistributionBuilder(Path(args.dir) / args.name)
            manifest = builder.init(
                name=args.name,
                version=args.version,
                vendor=args.vendor,
                platform=args.platform,
                profile=args.profile,
            )
            print(f"[OK] Distribution project initialized: {manifest}")

        elif args.command == "validate":
            builder = DistributionBuilder(args.dir)
            is_valid, issues = builder.validate()
            if is_valid:
                print("[OK] Distribution is valid")
            else:
                print("[ERROR] Distribution validation failed:")
                for issue in issues:
                    print(f"  - {issue}")
                return 1

        elif args.command == "build":
            builder = DistributionBuilder(args.dir)
            pkg = builder.build()
            print(f"[OK] Package built: {pkg} ({pkg.stat().st_size:,} bytes)")

        elif args.command == "test":
            builder = DistributionBuilder(args.dir)
            passed, report = builder.test()
            print(report)
            if not passed:
                return 1

        elif args.command == "sign":
            builder = DistributionBuilder(args.dir)
            sig = builder.sign(args.key)
            print(f"[OK] Package signed: {sig}")

    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[ERROR] Unexpected failure: {exc}", file=sys.stderr)
        return 2

    return 0


__all__ = [
    "DistributionManifest",
    "DistributionBuilder",
    "REFERENCE_DISTRIBUTIONS",
    "init_reference_distribution",
    "main",
]

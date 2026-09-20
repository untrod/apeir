# -*- coding: utf-8 -*-
"""
Pack Manifest parser and validator.

A pack.yaml file defines a Pack's identity, capabilities, providers,
dependencies, and configuration. This module parses and validates
manifests against a JSON schema.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from nous_runtime.yaml_compat import yaml

# JSON Schema for pack.yaml validation
MANIFEST_SCHEMA = {
    "type": "object",
    "required": ["name", "version", "description"],
    "properties": {
        "name": {
            "type": "string",
            "pattern": "^[a-z][a-z0-9_]*$",
            "description": "Pack identifier (snake_case)",
        },
        "version": {
            "type": "string",
            "pattern": r"^\d+\.\d+\.\d+$",
            "description": "Semantic version (e.g., 1.0.0)",
        },
        "description": {"type": "string"},
        "author": {"type": "string"},
        "license": {"type": "string"},
        "capabilities": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Capability IDs this pack provides",
        },
        "providers": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Provider names this pack registers",
        },
        "dependencies": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "Required packs and their version constraints",
        },
        "config": {
            "type": "object",
            "description": "Default configuration values",
        },
    },
}


@dataclass
class PackManifest:
    """Parsed and validated pack manifest."""

    name: str
    version: str
    description: str
    author: str = ""
    license: str = "Apache-2.0"
    capabilities: list[str] = field(default_factory=list)
    providers: list[str] = field(default_factory=list)
    dependencies: dict[str, str] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: str) -> "PackManifest":
        """
        Load and validate a pack manifest from a pack.yaml file.

        Args:
            path: Path to the pack directory or pack.yaml file.

        Returns:
            A validated PackManifest instance.

        Raises:
            FileNotFoundError: If no pack.yaml found.
            ValueError: If manifest is invalid.
        """
        if os.path.isdir(path):
            yaml_path = os.path.join(path, "pack.yaml")
        else:
            yaml_path = path

        if not os.path.isfile(yaml_path):
            raise FileNotFoundError(f"No pack.yaml found at {yaml_path}")

        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            raise ValueError(f"Invalid pack.yaml: expected a mapping, got {type(data).__name__}")

        errors = cls._validate(data)
        if errors:
            raise ValueError("Invalid pack manifest:\n" + "\n".join(f"  - {e}" for e in errors))

        return cls(
            name=data["name"],
            version=data["version"],
            description=data["description"],
            author=data.get("author", ""),
            license=data.get("license", "Apache-2.0"),
            capabilities=data.get("capabilities", []),
            providers=data.get("providers", []),
            dependencies=data.get("dependencies", {}),
            config=data.get("config", {}),
        )

    @classmethod
    def _validate(cls, data: dict) -> list[str]:
        """Run basic validation. Returns list of error messages."""
        errors = []

        if not data.get("name"):
            errors.append("'name' is required")
        elif not re.match(r"^[a-z][a-z0-9_]*$", data["name"]):
            errors.append(f"'name' must be snake_case: {data['name']}")

        if not data.get("version"):
            errors.append("'version' is required")
        elif not re.match(r"^\d+\.\d+\.\d+$", data["version"]):
            errors.append(f"'version' must be semver (X.Y.Z): {data['version']}")

        if not data.get("description"):
            errors.append("'description' is required")

        for cap in data.get("capabilities", []):
            if not re.match(r"^[a-z][a-z0-9_.]*$", cap):
                errors.append(f"Invalid capability name: '{cap}' (must be dot-separated lowercase)")

        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "license": self.license,
            "capabilities": self.capabilities,
            "providers": self.providers,
            "dependencies": self.dependencies,
            "config": self.config,
        }

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


def test_public_extension_contract_schemas_are_valid():
    project = Path(__file__).resolve().parents[2]
    schemas = [
        project
        / "spec"
        / "extensions"
        / "v1"
        / "extension-operation-receipt.schema.json",
        project
        / "spec"
        / "extensions"
        / "v1"
        / "extension-export-report.schema.json",
    ]

    for path in schemas:
        Draft202012Validator.check_schema(
            json.loads(path.read_text(encoding="utf-8"))
        )

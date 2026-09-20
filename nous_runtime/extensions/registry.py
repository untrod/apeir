"""Content-addressed extension registry with an auditable lock file."""

from __future__ import annotations

import json
import hashlib
import shutil
from pathlib import Path
from typing import Any

from nous_runtime.extensions.adapters import ExtensionInspector
from nous_runtime.extensions.models import ExtensionManifest
from nous_runtime.extensions.sources import (
    ExtensionSource,
    is_package_manifest,
    package_digest,
    package_files,
)
from nous_runtime.extensions.supply_chain import (
    create_supply_chain_records,
    sign_supply_chain_records,
    verify_supply_chain_records,
)


class ExtensionRegistry:
    """Install immutable source objects without enabling or executing them."""

    def __init__(self, root: str | Path, inspector: ExtensionInspector | None = None):
        self.root = Path(root).expanduser().resolve()
        self.objects = self.root / "objects"
        self.index_path = self.root / "registry.json"
        self.lock_path = self.root / "nous.extensions.lock.json"
        self.inspector = inspector or ExtensionInspector()

    def install(self, source: str | Path) -> ExtensionManifest:
        manifest = self.inspector.inspect(source)
        assert manifest.provenance is not None
        digest = manifest.provenance.digest.removeprefix("sha256:")
        object_root = self.objects / digest
        package_root = object_root / "package"
        object_created = not object_root.exists()
        if object_created:
            package_root.mkdir(parents=True, exist_ok=False)
            try:
                with ExtensionSource(source) as resolved:
                    standalone = resolved.preferred_file is not None and not is_package_manifest(
                        resolved.preferred_file
                    )
                    files = (
                        (resolved.preferred_file,) if standalone else package_files(resolved.root)
                    )
                    for path in files:
                        assert path is not None
                        relative = path.name if standalone else path.relative_to(resolved.root)
                        destination = package_root / relative
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(path, destination)
                _write_json(object_root / "nous.extension.json", manifest.to_dict())
                security = create_supply_chain_records(object_root, manifest)
            except Exception:
                shutil.rmtree(object_root, ignore_errors=True)
                raise
        else:
            stored = ExtensionManifest.from_dict(_read_json(object_root / "nous.extension.json"))
            if stored.provenance is None or stored.provenance.digest != manifest.provenance.digest:
                raise ValueError("content-addressed registry object does not match source digest")
            manifest = stored
            if not (object_root / "bom.json").exists():
                security = create_supply_chain_records(object_root, stored)
            else:
                existing = self._record_for_digest(manifest.provenance.digest)
                if existing:
                    security = verify_supply_chain_records(object_root, stored, existing)
                else:
                    security = self._evidence_metadata(object_root)
        projection_path = object_root / "kernel-admission-request.json"
        projection = _kernel_projection(manifest, security)
        if object_created:
            _write_json(projection_path, projection)
        else:
            current_projection = _read_json(projection_path)
            if current_projection == manifest.kernel_projection():
                _write_json(projection_path, projection)
            elif current_projection != projection:
                raise ValueError("Kernel admission projection was modified")

        index = self._index()
        records = index.setdefault("extensions", {})
        previous = records.get(manifest.extension_id) or {}
        records[manifest.extension_id] = {
            "version": manifest.version,
            "digest": manifest.provenance.digest,
            "source_format": manifest.source_format,
            "compatibility_level": int(manifest.compatibility_level),
            "state": "installed",
            "authority": "none",
            "previous_digest": str(previous.get("digest") or ""),
            "previous_granted_capabilities": list(
                previous.get("granted_capabilities") or ()
            ),
            "granted_capabilities": [],
            **security,
        }
        _write_json(self.index_path, index)
        self._write_lock(index)
        return self.verify(manifest.extension_id)

    def verify(self, extension_id: str) -> ExtensionManifest:
        """Verify index, lock, normalized manifest, admission projection, and source."""

        index = self._index()
        record = (index.get("extensions") or {}).get(extension_id)
        if not isinstance(record, dict):
            raise ValueError(f"extension is not installed: {extension_id}")
        lock = _read_json(self.lock_path)
        locked = {
            str(item.get("extension_id")): item
            for item in lock.get("extensions") or ()
            if isinstance(item, dict)
        }.get(extension_id)
        if not locked:
            raise ValueError("extension lock entry is missing")
        if locked.get("digest") != record.get("digest"):
            raise ValueError("extension lock digest does not match registry")
        for field in (
            "version",
            "source_format",
            "authority",
            "granted_capabilities",
            "normalized_ir_digest",
            "sbom_digest",
            "provenance_digest",
            "signature_status",
            "signature_digest",
        ):
            if locked.get(field) != record.get(field):
                raise ValueError(f"extension lock {field} does not match registry")
        digest = str(record.get("digest") or "")
        object_root = self.objects / digest.removeprefix("sha256:")
        manifest = ExtensionManifest.from_dict(
            _read_json(object_root / "nous.extension.json")
        ).require_valid()
        if manifest.provenance is None or manifest.provenance.digest != digest:
            raise ValueError("normalized manifest digest does not match registry")
        if package_digest(object_root / "package") != digest:
            raise ValueError("installed extension content digest mismatch")
        projection = _read_json(object_root / "kernel-admission-request.json")
        if projection != _kernel_projection(manifest, record):
            raise ValueError("Kernel admission projection was modified")
        verify_supply_chain_records(object_root, manifest, record)
        return manifest

    def admission_request(self, extension_id: str) -> dict[str, Any]:
        """Return the verified, supply-chain-bound projection for the Kernel."""

        manifest = self.verify(extension_id)
        assert manifest.provenance is not None
        object_root = self.objects / manifest.provenance.digest.removeprefix("sha256:")
        return _read_json(object_root / "kernel-admission-request.json")

    def sign(self, extension_id: str, private_key: str | Path) -> dict[str, str]:
        """Sign an installed extension without persisting the private key."""

        manifest = self.verify(extension_id)
        assert manifest.provenance is not None
        key_path = Path(private_key).expanduser().resolve()
        key_bytes = key_path.read_bytes()
        object_root = self.objects / manifest.provenance.digest.removeprefix("sha256:")
        security = sign_supply_chain_records(object_root, manifest, key_bytes)
        index = self._index()
        record = index["extensions"][extension_id]
        previous_grants = list(record.get("granted_capabilities") or ())
        record.update(security)
        record["previous_granted_capabilities"] = previous_grants
        record["granted_capabilities"] = []
        record["authority"] = "none"
        record["state"] = "installed"
        record.pop("admission_receipt", None)
        record.pop("policy_version", None)
        _write_json(
            object_root / "kernel-admission-request.json",
            _kernel_projection(manifest, security),
        )
        admission = object_root / "admission-decision.json"
        if admission.exists():
            admission.unlink()
        _write_json(self.index_path, index)
        self._write_lock(index)
        self.verify(extension_id)
        return security

    def record_admission(self, extension_id: str, decision: dict[str, Any]) -> None:
        """Persist a validated Kernel decision without expanding its grants."""

        manifest = self.verify(extension_id)
        assert manifest.provenance is not None
        if decision.get("normalized_digest") != manifest.provenance.digest:
            raise ValueError("admission digest does not match installed extension")
        object_root = self.objects / manifest.provenance.digest.removeprefix("sha256:")
        _write_json(object_root / "admission-decision.json", decision)
        index = self._index()
        record = index["extensions"][extension_id]
        record["state"] = (
            "approval_required" if decision.get("approval_required") else "admitted"
        )
        record["admission_receipt"] = str(decision.get("receipt_id") or "")
        record["policy_version"] = str(decision.get("policy_version") or "")
        record["granted_capabilities"] = list(
            decision.get("granted_capabilities") or ()
        )
        if record["granted_capabilities"]:
            record["authority"] = "kernel_grant"
            if not decision.get("approval_required"):
                record["state"] = "authorized"
        else:
            record["authority"] = "none"
        _write_json(self.index_path, index)
        self._write_lock(index)

    def record_revocation(self, extension_id: str, decision: dict[str, Any]) -> None:
        self.record_admission(extension_id, decision)
        index = self._index()
        record = index["extensions"][extension_id]
        record["state"] = "revoked"
        record["authority"] = "none"
        record.pop("pending_permission_request", None)
        _write_json(self.index_path, index)
        self._write_lock(index)

    def get_record(self, extension_id: str) -> dict[str, Any] | None:
        record = (self._index().get("extensions") or {}).get(extension_id)
        return dict(record) if isinstance(record, dict) else None

    def read_admission(self, extension_id: str) -> dict[str, Any] | None:
        record = self.get_record(extension_id)
        if not record:
            return None
        digest = str(record.get("digest") or "").removeprefix("sha256:")
        path = self.objects / digest / "admission-decision.json"
        return _read_json(path) if path.exists() else None

    def record_permission_request(
        self,
        extension_id: str,
        *,
        request_id: str,
        proposal_hash: str,
        capabilities: tuple[str, ...],
    ) -> None:
        self.verify(extension_id)
        index = self._index()
        record = index["extensions"][extension_id]
        record["pending_permission_request"] = {
            "request_id": request_id,
            "proposal_hash": proposal_hash,
            "digest": record["digest"],
            "capabilities": list(capabilities),
        }
        record["state"] = "approval_pending"
        _write_json(self.index_path, index)
        self._write_lock(index)

    def clear_permission_request(self, extension_id: str) -> None:
        index = self._index()
        record = (index.get("extensions") or {}).get(extension_id)
        if not isinstance(record, dict):
            raise ValueError(f"extension is not installed: {extension_id}")
        record.pop("pending_permission_request", None)
        _write_json(self.index_path, index)
        self._write_lock(index)

    def record_permission_approval(
        self,
        extension_id: str,
        *,
        request_id: str,
        proposal_hash: str,
        approval_id: str,
    ) -> None:
        index = self._index()
        record = (index.get("extensions") or {}).get(extension_id)
        if not isinstance(record, dict):
            raise ValueError(f"extension is not installed: {extension_id}")
        pending = record.get("pending_permission_request")
        if not isinstance(pending, dict) or pending.get("request_id") != request_id:
            raise ValueError("permission request is not pending for extension")
        if pending.get("proposal_hash") != proposal_hash:
            raise ValueError("approval proposal hash does not match pending request")
        pending["approval_id"] = approval_id
        _write_json(self.index_path, index)
        self._write_lock(index)

    def record_execution_receipt(
        self, extension_id: str, receipt: dict[str, Any]
    ) -> Path:
        """Persist result metadata without storing potentially sensitive output."""

        manifest = self.verify(extension_id)
        assert manifest.provenance is not None
        if receipt.get("content_digest") != manifest.provenance.digest:
            raise ValueError("execution receipt digest does not match installed extension")
        receipt_id = str(receipt.get("receipt_id") or "")
        if not receipt_id or any(value in receipt_id for value in ("/", "\\", "..")):
            raise ValueError("invalid execution receipt id")
        path = (
            self.objects
            / manifest.provenance.digest.removeprefix("sha256:")
            / "executions"
            / f"{receipt_id}.json"
        )
        if path.exists():
            if _read_json(path) != receipt:
                raise ValueError("execution receipt id collision")
            return path
        _write_json(path, receipt)
        return path

    def claim_execution(
        self, extension_id: str, operation_id: str, claim: dict[str, Any]
    ) -> Path:
        """Atomically reserve an operation so retries cannot repeat a side effect."""

        manifest = self.verify(extension_id)
        assert manifest.provenance is not None
        if claim.get("content_digest") != manifest.provenance.digest:
            raise ValueError("execution claim digest does not match installed extension")
        if not operation_id or any(value in operation_id for value in ("/", "\\", "..")):
            raise ValueError("invalid extension operation id")
        path = (
            self.objects
            / manifest.provenance.digest.removeprefix("sha256:")
            / "executions"
            / "claims"
            / f"{operation_id}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(claim, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
        except FileExistsError as exc:
            existing = _read_json(path)
            receipt_id = str(existing.get("receipt_id") or "indeterminate")
            raise ValueError(
                f"extension operation was already claimed; receipt={receipt_id}"
            ) from exc
        return path

    def complete_execution_claim(
        self, extension_id: str, operation_id: str, receipt_id: str
    ) -> None:
        manifest = self.verify(extension_id)
        assert manifest.provenance is not None
        path = (
            self.objects
            / manifest.provenance.digest.removeprefix("sha256:")
            / "executions"
            / "claims"
            / f"{operation_id}.json"
        )
        if not path.is_file():
            raise ValueError("extension execution claim is missing")
        claim = _read_json(path)
        if claim.get("operation_id") != operation_id:
            raise ValueError("extension execution claim identity mismatch")
        claim["state"] = "completed"
        claim["receipt_id"] = receipt_id
        _write_json(path, claim)

    def record_discovered_tools(
        self,
        extension_id: str,
        tools: list[dict[str, Any]],
        *,
        discovery_receipt_id: str,
    ) -> None:
        manifest = self.verify(extension_id)
        assert manifest.provenance is not None
        names = [str(item.get("name") or "") for item in tools]
        if not names or any(not name for name in names) or len(names) != len(set(names)):
            raise ValueError("discovered MCP tools require unique non-empty names")
        catalog = {
            "schema": "nous.mcp-tool-catalog/v1",
            "extension_id": extension_id,
            "content_digest": manifest.provenance.digest,
            "discovery_receipt_id": discovery_receipt_id,
            "tools": tools,
        }
        encoded = _canonical_json(catalog)
        catalog_digest = "sha256:" + hashlib.sha256(encoded).hexdigest()
        object_root = self.objects / manifest.provenance.digest.removeprefix("sha256:")
        _write_json(object_root / "mcp-tool-catalog.json", catalog)
        index = self._index()
        record = index["extensions"][extension_id]
        record["mcp_catalog_digest"] = catalog_digest
        record["mcp_discovery_receipt"] = discovery_receipt_id
        _write_json(self.index_path, index)
        self._write_lock(index)

    def read_discovered_tools(self, extension_id: str) -> list[dict[str, Any]]:
        manifest = self.verify(extension_id)
        record = self.get_record(extension_id)
        assert manifest.provenance is not None and record is not None
        path = (
            self.objects
            / manifest.provenance.digest.removeprefix("sha256:")
            / "mcp-tool-catalog.json"
        )
        if not path.exists():
            return []
        catalog = _read_json(path)
        expected = str(record.get("mcp_catalog_digest") or "")
        actual = "sha256:" + hashlib.sha256(_canonical_json(catalog)).hexdigest()
        if not expected or actual != expected:
            raise ValueError("MCP tool catalog integrity check failed")
        if (
            catalog.get("extension_id") != extension_id
            or catalog.get("content_digest") != manifest.provenance.digest
            or catalog.get("discovery_receipt_id")
            != record.get("mcp_discovery_receipt")
        ):
            raise ValueError("MCP tool catalog binding check failed")
        tools = catalog.get("tools")
        if not isinstance(tools, list) or any(not isinstance(item, dict) for item in tools):
            raise ValueError("MCP tool catalog is invalid")
        return [dict(item) for item in tools]

    def list(self) -> list[dict[str, Any]]:
        records = self._index().get("extensions") or {}
        return [
            {"extension_id": extension_id, **record}
            for extension_id, record in sorted(records.items())
        ]

    def get(self, extension_id: str) -> ExtensionManifest | None:
        record = (self._index().get("extensions") or {}).get(extension_id)
        if not record:
            return None
        digest = str(record["digest"]).removeprefix("sha256:")
        path = self.objects / digest / "nous.extension.json"
        return ExtensionManifest.from_dict(_read_json(path)).require_valid()

    def package_path(self, extension_id: str) -> Path:
        """Return the verified immutable package root for an installed extension."""

        manifest = self.verify(extension_id)
        assert manifest.provenance is not None
        digest = manifest.provenance.digest.removeprefix("sha256:")
        return self.objects / digest / "package"

    def remove(self, extension_id: str) -> bool:
        """Remove a registry reference; immutable objects remain for rollback/audit."""

        index = self._index()
        records = index.get("extensions") or {}
        if extension_id not in records:
            return False
        del records[extension_id]
        _write_json(self.index_path, index)
        self._write_lock(index)
        return True

    def _index(self) -> dict[str, Any]:
        if not self.index_path.exists():
            return {"schema": "nous.extension-registry/v1", "extensions": {}}
        data = _read_json(self.index_path)
        if data.get("schema") != "nous.extension-registry/v1" or not isinstance(data.get("extensions"), dict):
            raise ValueError("invalid extension registry index")
        return data

    def _record_for_digest(self, digest: str) -> dict[str, Any] | None:
        for record in (self._index().get("extensions") or {}).values():
            if isinstance(record, dict) and record.get("digest") == digest:
                return record
        return None

    @staticmethod
    def _evidence_metadata(object_root: Path) -> dict[str, str]:
        provenance = _read_json(object_root / "provenance.json")
        signature = _read_json(object_root / "signature.json")
        bom = _read_json(object_root / "bom.json")
        return {
            "normalized_ir_digest": str(provenance.get("normalized_ir_digest") or ""),
            "sbom_digest": "sha256:" + hashlib.sha256(_canonical_json(bom)).hexdigest(),
            "provenance_digest": "sha256:" + hashlib.sha256(_canonical_json(provenance)).hexdigest(),
            "signature_status": str(signature.get("status") or "Unknown"),
            "signature_digest": "sha256:" + hashlib.sha256(_canonical_json(signature)).hexdigest(),
        }

    def _write_lock(self, index: dict[str, Any]) -> None:
        locked = []
        for extension_id, record in sorted((index.get("extensions") or {}).items()):
            manifest = self.get(extension_id)
            if manifest is None:
                continue
            locked.append(
                {
                    "extension_id": extension_id,
                    "version": record["version"],
                    "digest": record["digest"],
                    "source_format": record["source_format"],
                    "authority": record.get("authority", "none"),
                    "granted_capabilities": list(
                        record.get("granted_capabilities") or ()
                    ),
                    "capability_requests": [item.__dict__ for item in manifest.capabilities],
                    "normalized_ir_digest": record.get("normalized_ir_digest", ""),
                    "sbom_digest": record.get("sbom_digest", ""),
                    "provenance_digest": record.get("provenance_digest", ""),
                    "signature_status": record.get("signature_status", "Unknown"),
                    "signature_digest": record.get("signature_digest", ""),
                }
            )
        _write_json(
            self.lock_path,
            {"schema": "nous.extension-lock/v1", "extensions": locked},
        )


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _canonical_json(data: dict[str, Any]) -> bytes:
    return json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _kernel_projection(
    manifest: ExtensionManifest, evidence: dict[str, Any]
) -> dict[str, Any]:
    projection = manifest.kernel_projection()
    projection["metadata"].update(
        {
            "supply_chain_verified": "true",
            "normalized_ir_digest": str(evidence.get("normalized_ir_digest") or ""),
            "sbom_digest": str(evidence.get("sbom_digest") or ""),
            "provenance_digest": str(evidence.get("provenance_digest") or ""),
            "signature_status": str(evidence.get("signature_status") or "Unknown"),
            "signature_digest": str(evidence.get("signature_digest") or ""),
        }
    )
    return projection

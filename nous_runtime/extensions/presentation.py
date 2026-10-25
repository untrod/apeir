"""Restricted Studio host over the existing Extension Registry and Runtime.

Only declarative data is admitted. This service neither executes package code
nor turns installation/presentation enablement into a Capability grant.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import uuid

from nous_runtime.extensions.adapters import ExtensionInspector
from nous_runtime.extensions.models import ExtensionManifest
from nous_runtime.extensions.presentation_contract import (
    FIELDS,
    component_type,
    validate_presentation,
)
from nous_runtime.extensions.registry import ExtensionRegistry
from nous_runtime.security.private_files import validate_private_database_path


def _json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate manifest field")
        value[key] = item
    return value


def _nonfinite(value):
    raise ValueError("Nonfinite manifest number")


class StudioExtensionHost:
    """Presentation adapter; Registry/Governance/Workflow remain their owners."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        # Reuse static private-state path admission. No guarantee is made against
        # a trusted OS owner replacing paths after admission.
        for directory in (
            self.root / ".nous",
            self.root / ".nous" / "extensions",
            self.root / ".nous" / "artifacts",
        ):
            validate_private_database_path(directory / ".studio-path-admission")
        self.registry = ExtensionRegistry(self.root / ".nous" / "extensions")

    @contextmanager
    def _staged(self, source_manifest: str):
        if (
            not isinstance(source_manifest, str)
            or not 1 <= len(source_manifest.encode("utf-8")) <= 128 * 1024
        ):
            raise ValueError("A UTF-8 manifest of at most 128 KiB is required")
        value = json.loads(
            source_manifest, object_pairs_hook=_json_object, parse_constant=_nonfinite
        )
        allowed = {
            "schema",
            "extension_id",
            "version",
            "description",
            "source_format",
            "compatibility_level",
            "kinds",
            "skills",
            "tools",
            "capabilities",
            "entry_points",
            "dependencies",
            "license",
            "metadata",
            "provenance",
        }
        if not isinstance(value, dict) or set(value) - allowed:
            raise ValueError("Unsupported native Extension manifest field")
        from nous_runtime.core.redaction import redact_sensitive_data

        if redact_sensitive_data(value) != value:
            raise ValueError("Sensitive material cannot enter a Studio package")
        required = {
            "schema",
            "extension_id",
            "version",
            "description",
            "source_format",
            "compatibility_level",
            "kinds",
        }
        if required - set(value) or any(
            not isinstance(value.get(key), str)
            for key in (
                "schema",
                "extension_id",
                "version",
                "description",
                "source_format",
            )
        ):
            raise ValueError("Invalid native UI manifest identity")
        if (
            type(value["compatibility_level"]) is not int
            or value["compatibility_level"] != 2
            or value["source_format"] != "nous-native-v1"
        ):
            raise ValueError(
                "UI packages declare native IMPORT compatibility only, not certification"
            )
        if value["kinds"] not in (["plugin"], ["template"]):
            raise ValueError("UI package kind must be plugin or template")
        for key in ("entry_points", "tools", "skills", "capabilities"):
            if not isinstance(value.get(key, []), list):
                raise ValueError("Invalid native UI manifest list")
        if not isinstance(value.get("metadata"), dict) or set(value["metadata"]) - {
            "apeir_studio",
            "publisher",
        }:
            raise ValueError("Unsupported UI package metadata")
        if "publisher" in value["metadata"] and (
            not isinstance(value["metadata"]["publisher"], str)
            or len(value["metadata"]["publisher"]) > 128
        ):
            raise ValueError("Invalid unverified publisher description")
        manifest = ExtensionManifest.from_dict(value).require_valid()
        declared = {item.capability: item.access for item in manifest.capabilities}
        if set(declared) - {
            "runtime.status.read",
            "runtime.lifecycle.read",
            "workflow.run",
        }:
            raise ValueError("Unsupported Studio permission request")

        def has_action(view):
            return view["kind"] == "action" or any(
                has_action(child) for child in view.get("children", [])
            )

        for contribution in manifest.metadata["apeir_studio"]["contributions"]:
            if (
                has_action(contribution["view"])
                and declared.get("workflow.run") != "execute"
            ):
                raise ValueError(
                    "Workflow action requires its explicit execute request; it is not a grant"
                )
            for source in contribution.get("subscriptions", []):
                if (
                    declared.get(
                        {
                            "runtime.status": "runtime.status.read",
                            "runtime.lifecycle": "runtime.lifecycle.read",
                        }[source]
                    )
                    != "read"
                ):
                    raise ValueError(
                        "A data subscription requires its explicit read request; it is not a grant"
                    )
        if (
            "apeir_studio" not in manifest.metadata
            or manifest.entry_points
            or manifest.tools
            or manifest.skills
        ):
            raise ValueError(
                "This importer accepts declarative UI manifests without executable entry points or tools"
            )
        if len(manifest.capabilities) > 32 or len(manifest.dependencies) > 16:
            raise ValueError("Studio package declaration exceeds its bounds")
        with tempfile.TemporaryDirectory(prefix="apeir-studio-package-") as folder:
            path = Path(folder)
            (path / "nous.extension.json").write_text(source_manifest, encoding="utf-8")
            inspected = ExtensionInspector().inspect(path)
            yield path, inspected

    def _dependencies(self, manifest):
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version

        for extension_id, constraint in manifest.dependencies.items():
            dependency = self.registry.verify(extension_id)
            record = self.registry.get_record(extension_id) or {}
            if record.get("state") == "revoked":
                raise PermissionError("Required extension is revoked")
            specifier = (
                constraint
                if any(marker in constraint for marker in "<>=!~")
                else "==" + constraint
            )
            if Version(dependency.version) not in SpecifierSet(specifier):
                raise ValueError("Required extension version is incompatible")

    def review(self, source_manifest):
        with self._staged(source_manifest) as (_, manifest):
            previous = self.registry.get_record(manifest.extension_id) or {}
            self._check_existing(manifest, previous)
            self._dependencies(manifest)
            return {
                "manifest": manifest.to_dict(),
                "digest": manifest.provenance.digest,
                "extension_id": manifest.extension_id,
                "version": manifest.version,
                "previous_digest": previous.get("digest", ""),
                "previous_version": previous.get("version", ""),
                "review_state": "REVIEW_REQUIRED",
                "publisher_trust": "UNVERIFIED",
                "executable_ui": "BLOCKED",
                "authority": "none",
            }

    def install(
        self,
        source_manifest,
        *,
        expected_digest,
        expected_previous_digest,
        before_publish=None,
    ):
        from nous_runtime.artifact.content_store import ContentAddressedArtifactStore
        from nous_runtime.artifact.models import ArtifactType

        with (
            self._staged(source_manifest) as (path, manifest),
            self.registry._writer_lock(),
        ):
            digest = manifest.provenance.digest
            if digest != expected_digest:
                raise PermissionError("Package differs from the reviewed digest")
            previous = self.registry.get_record(manifest.extension_id) or {}
            self._check_existing(manifest, previous)
            if previous.get("digest", "") != expected_previous_digest:
                raise PermissionError(
                    "Installed version changed; review the package again"
                )
            self._dependencies(manifest)
            if before_publish is not None:
                before_publish()
            if previous.get("digest") == digest:
                self.registry.verify(manifest.extension_id)
                return self.record(manifest.extension_id)
            store = ContentAddressedArtifactStore(self.root / ".nous" / "artifacts")
            artifact = store.store_bytes(
                source_manifest.encode("utf-8"),
                artifact_type=ArtifactType.SOURCE_BUNDLE,
                name="studio-ui-manifest.json",
                media_type="application/vnd.apeir.studio-ui+json",
                produced_by="apeir.studio-extension-host",
                metadata={
                    "extension_id": manifest.extension_id,
                    "version": manifest.version,
                    "package_digest": digest,
                    "authority": "none",
                },
            )
            reference = artifact["artifact"]["digest"]
            attempt_owner = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
            installed_owner = self._pin_owner(manifest.extension_id)
            store.pin(reference, reason="installed-declarative-ui", owner=attempt_owner)
            published = retained = False
            try:
                self.registry.install(
                    path, artifact_ref=reference, before_publish=before_publish
                )
                published = True
                store.pin(
                    reference, reason="installed-declarative-ui", owner=installed_owner
                )
                retained = True
            finally:
                if not published or retained:
                    store.unpin(reference, owner=attempt_owner)
            old_ref = previous.get("artifact_ref")
            if old_ref and old_ref != reference:
                store.unpin(old_ref, owner=installed_owner)
            return self.record(manifest.extension_id)

    def _check_existing(self, manifest, previous):
        if previous:
            old = self.registry.verify(manifest.extension_id)
            if "apeir_studio" not in old.metadata:
                raise PermissionError(
                    "A non-UI extension identity requires an explicit migration"
                )
            if (
                old.version == manifest.version
                and previous["digest"] != manifest.provenance.digest
            ):
                raise ValueError("Studio version already refers to different content")
            if previous.get("state") == "revoked":
                raise PermissionError(
                    "Revoked UI identity requires explicit authority restoration"
                )

    @staticmethod
    def _pin_owner(extension_id):
        return hashlib.sha256(("studio-ui:" + extension_id).encode()).hexdigest()

    def configure(
        self,
        extension_id,
        *,
        enabled,
        expected_digest,
        expected_version,
        before_publish=None,
    ):
        self.registry.set_presentation_enabled(
            extension_id,
            enabled,
            expected_digest=expected_digest,
            expected_version=expected_version,
            before_publish=before_publish,
        )
        return self.record(extension_id)

    def remove(
        self, extension_id, *, expected_digest, expected_version, before_remove=None
    ):
        from nous_runtime.artifact.content_store import ContentAddressedArtifactStore

        with self.registry._writer_lock():
            self.record(
                extension_id
            )  # A presentation API cannot uninstall another extension kind.
            previous = self.registry.get_record(extension_id) or {}
            removed = self.registry.remove(
                extension_id,
                expected_digest=expected_digest,
                expected_version=expected_version,
                before_remove=before_remove,
            )
            if removed and previous.get("artifact_ref"):
                ContentAddressedArtifactStore(self.root / ".nous" / "artifacts").unpin(
                    previous["artifact_ref"], owner=self._pin_owner(extension_id)
                )
            return {"removed": removed, "extension_id": extension_id}

    def record(self, extension_id):
        manifest = self.registry.verify(extension_id)
        record = self.registry.get_record(extension_id) or {}
        ui = validate_presentation(manifest.metadata["apeir_studio"])
        return {
            "extension_id": extension_id,
            "version": manifest.version,
            "digest": record["digest"],
            "enabled": record.get("presentation_enabled") is True
            and record.get("state") != "revoked",
            "state": record.get("state"),
            "authority": record.get("authority", "none"),
            "granted_capabilities": record.get("granted_capabilities", []),
            "signature_status": record.get("signature_status", "Unknown"),
            "publisher_trust": "UNVERIFIED",
            "artifact_ref": record.get("artifact_ref", ""),
            "contributions": [
                {**item, "type": component_type(extension_id, item["id"])}
                for item in ui["contributions"]
            ],
        }

    def records(self):
        result, diagnostics = [], []
        for record in self.registry.list():
            extension_id = record["extension_id"]
            try:
                manifest = self.registry.verify(extension_id)
                if "apeir_studio" in manifest.metadata:
                    result.append(self.record(extension_id))
            except (ValueError, OSError, PermissionError) as error:
                diagnostics.append(
                    {
                        "extension_id": extension_id,
                        "state": "BLOCKED",
                        "reason": type(error).__name__,
                    }
                )
        if len(result) > 64:
            raise ValueError("Studio extension index exceeds its bounded profile")
        return result, diagnostics

    def _contribution(self, component, expected_digest):
        for record in self.registry.list():
            extension_id = record["extension_id"]
            # Stable presentation identity is not a resource or permission grant.
            if not component.startswith(
                "ui:" + hashlib.sha256(extension_id.encode()).hexdigest()[:32] + ":"
            ):
                continue
            current = self.record(extension_id)
            if current["digest"] != expected_digest or not current["enabled"]:
                raise PermissionError("Extension is changed, disabled or revoked")
            contribution = next(
                (
                    item
                    for item in current["contributions"]
                    if item["type"] == component
                ),
                None,
            )
            if contribution is None:
                raise PermissionError("Extension contribution is unavailable")
            return current, contribution
        raise PermissionError("Extension contribution is not installed")

    @staticmethod
    def _status():
        from nous_runtime.api.routes import handle_status

        response = handle_status()
        if not response.get("ok"):
            raise RuntimeError("Authoritative Runtime status is unavailable")
        source = response["data"]
        kernel = source.get("kernel") or {}
        values = {
            key: source.get(key) for key in FIELDS if not key.startswith("kernel_")
        }
        values.update(
            kernel_state=kernel.get("state"), kernel_ready=kernel.get("ready")
        )
        return {
            key: value
            if value is None or type(value) in {bool, int, float, str}
            else None
            for key, value in values.items()
        }

    def read_data(self, component, expected_digest, source):
        with self.registry._writer_lock():
            _, contribution = self._contribution(component, expected_digest)
            if source not in contribution.get("subscriptions", []):
                raise PermissionError("Data source was not declared")
            if source != "runtime.status":
                raise ValueError(
                    "Use the allowed-events interface for lifecycle events"
                )
            return {
                "source": source,
                "values": self._status(),
                "received_at": datetime.now(timezone.utc).isoformat(),
                "execution_scope": "runtime-service",
                "verification": "NOT_PHYSICAL_VERIFICATION",
            }

    def read_events(self, component, expected_digest):
        from nous_runtime.events.bus import get_event_bus

        with self.registry._writer_lock():
            _, contribution = self._contribution(component, expected_digest)
            if "runtime.lifecycle" not in contribution.get("subscriptions", []):
                raise PermissionError("Lifecycle events were not declared")
            events = []
            for event_type in contribution.get("events", []):
                for event in get_event_bus(str(self.root)).query(
                    event_type=event_type, limit=16
                ):
                    events.append(
                        {
                            key: event.get(key)
                            for key in ("event_id", "event_type", "source", "timestamp")
                        }
                    )
            return {
                "events": sorted(events, key=lambda event: event["timestamp"] or "")[
                    -32:
                ]
            }

    def view(self):
        with self.registry._writer_lock():
            records, diagnostics = self.records()
            status = None
            if any(
                record["enabled"]
                and any(
                    "runtime.status" in item.get("subscriptions", [])
                    for item in record["contributions"]
                )
                for record in records
            ):
                status = self._status()
            return {
                "extensions": records,
                "diagnostics": diagnostics,
                "status": status,
                "received_at": datetime.now(timezone.utc).isoformat(),
                "executable_ui": "BLOCKED",
                "execution_scope": "runtime-service",
                "verification": "NOT_PHYSICAL_VERIFICATION",
            }

    def request_action(self, component, expected_digest, action, *, idempotency_key):
        from nous_runtime.workflow import WorkflowRuntime
        from nous_runtime.workflow.store import WorkflowStore

        if (
            not isinstance(idempotency_key, str)
            or not idempotency_key
            or len(idempotency_key) > 128
        ):
            raise ValueError("An original idempotency key is required")
        with self.registry._writer_lock():
            _, contribution = self._contribution(component, expected_digest)

            def actions(view):
                return ([view] if view.get("kind") == "action" else []) + [
                    found
                    for child in view.get("children", [])
                    for found in actions(child)
                ]

            candidates = [
                item
                for item in actions(contribution["view"])
                if item["action"] == action
            ]
            if len(candidates) != 1 or action != "workflow.run":
                raise PermissionError(
                    "Action was not uniquely declared by this contribution"
                )
            params = candidates[0]["params"]
            runtime = WorkflowRuntime(str(self.root))
            definition = runtime.store.get_definition(
                params["workflow_id"], params["version"]
            )
            if definition is None:
                raise ValueError("Original Workflow definition is not registered")
            runtime.compiler.validate(definition)
            if not 1 <= len(definition.steps) <= 64:
                raise PermissionError(
                    "Workflow exceeds the bounded Studio host profile"
                )
            for step in definition.steps:
                handler, policy = runtime._handler(step)
                if (
                    handler != runtime._builtin_handler
                    or policy.contract is None
                    or policy.contract.side_effect_class != "none"
                    or step.action
                    or step.condition
                    or step.compensation
                ):
                    raise PermissionError(
                        "This Studio action requires a bound pure Workflow host"
                    )
            run = runtime.start(
                definition.workflow_id,
                definition.version,
                params.get("inputs", {}),
                idempotency_key=idempotency_key,
            )
            result = WorkflowStore._run_dict(run)
            result["inputs"] = {
                key: value
                for key, value in run.inputs.items()
                if not key.startswith("_")
            }
            return {
                **result,
                "execution_scope": "runtime-service",
                "verification": "NOT_PHYSICAL_VERIFICATION",
            }

"""Unified Skill discovery and installation over existing Runtime mechanisms."""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import tempfile
import zipfile
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping

from nous_runtime.artifact.content_store import ContentAddressedArtifactStore
from nous_runtime.artifact.models import ArtifactType
from nous_runtime.extensions import ExtensionInspector, ExtensionRegistry
from nous_runtime.extensions.models import ExtensionManifest
from nous_runtime.extensions.sources import (
    ExtensionSource,
    is_package_manifest,
    package_files,
)
from nous_runtime.locking import file_lock
from nous_runtime.skills.models import SkillRecord
from nous_runtime.skills.remote import require_remote_url


_STATE_SCHEMA = "apeir.skill-registry-state/v1"
_CATALOG_SCHEMA = "apeir.skill-catalog/v1"
_MAX_CATALOG_BYTES = 1024 * 1024
_MAX_CATALOG_SKILLS = 512
_PROVIDER_PRIORITY = {
    "project": 50,
    "installed": 40,
    "user": 30,
    "builtin": 20,
    "catalog": 10,
}


class SkillRegistry:
    """Aggregate Skill providers without turning Skill metadata into permission."""

    def __init__(
        self,
        workspace: str | Path = ".",
        *,
        builtin_dir: str | Path | None = None,
        user_dir: str | Path | None = None,
        project_dir: str | Path | None = None,
        extension_registry: str | Path | None = None,
        artifact_root: str | Path | None = None,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.builtin_dir = (
            Path(builtin_dir).expanduser().resolve()
            if builtin_dir is not None
            else Path(__file__).parents[2] / "remote_terminal" / "skills"
        )
        nous_home = Path(os.environ.get("NOUS_HOME") or Path.home() / ".nous")
        self.user_dir = (
            Path(user_dir).expanduser().resolve()
            if user_dir is not None
            else nous_home / "skills"
        )
        self.project_dir = (
            Path(project_dir).expanduser().resolve()
            if project_dir is not None
            else self.workspace / ".nous" / "skills"
        )
        registry_root = (
            Path(extension_registry).expanduser().resolve()
            if extension_registry is not None
            else self.workspace / ".nous" / "extensions"
        )
        self.extensions = ExtensionRegistry(registry_root)
        self.artifact_root = (
            Path(artifact_root).expanduser().resolve()
            if artifact_root is not None
            else self.workspace / ".nous" / "artifacts"
        )
        self.state_path = self.workspace / ".nous" / "skills.json"
        self.diagnostics: list[dict[str, str]] = []

    def list(
        self, *, include_disabled: bool = False, include_catalogs: bool = True
    ) -> list[SkillRecord]:
        records = self._local_records()
        records.extend(self._installed_records())
        if include_catalogs:
            records.extend(self._catalog_records())
        records = [self._apply_state(record) for record in records]
        if not include_disabled:
            records = [record for record in records if record.enabled]
        return sorted(
            records,
            key=lambda item: (
                item.skill_id.casefold(),
                -_PROVIDER_PRIORITY.get(item.provider, 0),
                item.provider,
            ),
        )

    def summaries(self, *, include_disabled: bool = False) -> list[dict[str, Any]]:
        return [item.summary() for item in self._effective(include_disabled).values()]

    def search(self, query: str) -> list[SkillRecord]:
        terms = [item for item in str(query or "").casefold().split() if item]
        candidates = self._effective(include_disabled=False).values()
        if not terms:
            return list(candidates)
        scored: list[tuple[int, SkillRecord]] = []
        for item in candidates:
            name = f"{item.skill_id} {item.name}".casefold()
            content = " ".join(
                (
                    name,
                    item.description,
                    " ".join(item.tags),
                    " ".join(item.requested_capabilities),
                )
            ).casefold()
            score = sum(4 if term in name else 1 for term in terms if term in content)
            if score:
                scored.append((score, item))
        return [
            item
            for _, item in sorted(
                scored,
                key=lambda value: (-value[0], value[1].skill_id, value[1].provider),
            )
        ]

    def resolve(self, skill_id: str, *, include_disabled: bool = False) -> SkillRecord:
        requested = str(skill_id or "").strip()
        if not requested:
            raise ValueError("skill_id is required")
        provider = ""
        if ":" in requested:
            provider, requested = requested.split(":", 1)
        matches = [
            item
            for item in self.list(include_disabled=include_disabled)
            if item.skill_id == requested
            and (not provider or item.provider == provider)
        ]
        if not matches:
            raise KeyError(skill_id)
        preferred = max(_PROVIDER_PRIORITY.get(item.provider, 0) for item in matches)
        selected = [
            item
            for item in matches
            if _PROVIDER_PRIORITY.get(item.provider, 0) == preferred
        ]
        if selected[0].provider == "installed" and len(selected) != 1:
            raise ValueError(
                "Installed Skill identity is ambiguous; review its imports"
            )
        return selected[0]

    def load(self, skill_id: str) -> SkillRecord:
        """Load full instructions and resource names without executing resources."""

        record = self.resolve(skill_id)
        if record.provider == "catalog":
            raise ValueError("catalog skills must be installed before loading")
        return record

    def install(
        self,
        source: str | Path,
        *,
        expected: SkillRecord | None = None,
        before_publish: Callable[[], None] | None = None,
    ) -> SkillRecord:
        """Inspect, copy, evidence, and register a Skill without executing scripts."""

        # Snapshot bounded source bytes first. The exact reviewed snapshot, CAS
        # bundle and Extension object must agree before either index is visible.
        with tempfile.TemporaryDirectory(prefix="apeir-skill-install-") as temporary:
            with ExtensionSource(source) as resolved:
                package_root = Path(temporary) / resolved.root.name
                package_root.mkdir()
                standalone = (
                    resolved.preferred_file is not None
                    and not is_package_manifest(resolved.preferred_file)
                )
                files = (
                    (resolved.preferred_file,)
                    if standalone
                    else package_files(resolved.root)
                )
                for original in files:
                    target = package_root / original.relative_to(resolved.root)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(original, target)
                staged = (
                    package_root / resolved.preferred_file.relative_to(resolved.root)
                    if standalone
                    else package_root
                )
            manifest = ExtensionInspector().inspect(staged)
            self._require_skill_manifest(manifest)
            assert manifest.provenance is not None
            previous = self.extensions.get_record(manifest.extension_id)
            if previous and previous.get("state") == "revoked":
                raise PermissionError(
                    "Revoked Skill requires an explicit authority restoration, not reinstall"
                )
            if expected is not None and (
                manifest.skills[0].name != expected.skill_id
                or manifest.version != expected.version
                or manifest.provenance.digest != expected.digest
                or tuple(sorted({item.capability for item in manifest.capabilities}))
                != tuple(sorted(expected.requested_capabilities))
            ):
                raise ValueError(
                    "Skill content differs from the reviewed catalog entry"
                )
            store = ContentAddressedArtifactStore(self.artifact_root)
            artifact = store.store_bytes(
                _deterministic_bundle(package_root),
                artifact_type=ArtifactType.SOURCE_BUNDLE,
                name=f"{manifest.skills[0].name}-{manifest.version}.skill.zip",
                media_type="application/vnd.apeir.skill-bundle+zip",
                produced_by="apeir.skill-registry",
                metadata={
                    "extension_id": manifest.extension_id,
                    "skill_id": manifest.skills[0].name,
                    "version": manifest.version,
                    "package_digest": manifest.provenance.digest,
                    "authority": "none",
                },
            )
            artifact_ref = str(artifact["artifact"]["digest"])
            store.pin(artifact_ref, reason=f"installed-skill:{manifest.extension_id}")

            def revalidate_publication():
                if before_publish is not None:
                    before_publish()
                current = self.extensions.get_record(manifest.extension_id)
                if current and current.get("state") == "revoked":
                    raise PermissionError(
                        "Skill Extension was revoked during acquisition"
                    )
                for existing in self.extensions.list():
                    if existing["extension_id"] == manifest.extension_id:
                        continue
                    stored = self.extensions.verify(existing["extension_id"])
                    if any(
                        item.name == manifest.skills[0].name for item in stored.skills
                    ):
                        raise PermissionError(
                            "Installed Skill identity conflicts with another import; "
                            "review an explicit migration first"
                        )

            installed = self.extensions.install(
                staged, artifact_ref=artifact_ref, before_publish=revalidate_publication
            )
        # Existing enable/disable state survives updates. New Skills have the
        # existing enabled default; neither case grants execution permission.
        assert installed.provenance is not None
        published = [
            record
            for record in self._installed_records()
            if record.metadata["extension_id"] == installed.extension_id
            and record.skill_id == installed.skills[0].name
            and record.version == installed.version
            and record.digest == installed.provenance.digest
            and record.artifact_ref == artifact_ref
        ]
        if len(published) != 1:
            raise ValueError(
                "Published Skill content does not match its original install"
            )
        return self._apply_state(published[0])

    def catalog_records(self, *, local_only: bool = False) -> list[SkillRecord]:
        """Inspect registered catalogs; passive UI polling never fetches URLs."""
        return self._catalog_records(local_only=local_only)

    def install_from_catalog(
        self,
        skill_id: str,
        *,
        catalog_source: str,
        version: str,
        digest: str,
        before_publish: Callable[[], None] | None = None,
        authorize_remote: Callable[[str], None] | None = None,
        package_source: str = "",
    ) -> SkillRecord:
        if catalog_source not in self.catalogs():
            raise PermissionError(
                "Catalog must first be registered by the workspace owner"
            )
        remote = "://" in catalog_source
        candidates = [
            item
            for item in self.catalog_records(local_only=True)
            if item.skill_id == skill_id
            and item.metadata.get("catalog_source") == catalog_source
        ]
        if len(candidates) != 1:
            raise ValueError("Catalog entry is missing or ambiguous")
        entry = candidates[0]
        if (
            entry.version != version
            or entry.digest != digest
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
        ):
            raise ValueError("Catalog version or digest changed; review it again")
        if remote:
            if package_source != entry.source:
                raise ValueError("Skill package source changed; review it again")
            require_remote_url(catalog_source)
            require_remote_url(package_source)
            self._require_remote_authority(before_publish, authorize_remote)
            assert before_publish is not None and authorize_remote is not None

            def revalidate():
                if catalog_source not in self.catalogs():
                    raise PermissionError(
                        "Skill catalog was removed during acquisition"
                    )
                before_publish()
                authorize_remote(catalog_source)
                authorize_remote(package_source)
                current = [
                    item
                    for item in self.catalog_records(local_only=True)
                    if item.skill_id == skill_id
                    and item.metadata.get("catalog_source") == catalog_source
                ]
                if current != [entry]:
                    raise PermissionError(
                        "Skill catalog review changed during acquisition"
                    )

            revalidate()
            # Reacquire the original catalog; a cached review is never a network
            # or package permission and cannot hide a changed remote binding.
            live = self._read_catalog(catalog_source, allow_remote=True)
            live_entries = [
                _catalog_record(raw, catalog_source)
                for raw in live["skills"]
                if isinstance(raw, Mapping)
                and str(raw.get("name") or raw.get("skill_id") or "").strip()
                == skill_id
            ]
            if len(live_entries) != 1 or live_entries[0] != entry:
                raise ValueError("Skill catalog entry changed; review it again")
            revalidate()
            content = self._remote_bytes(package_source, max_bytes=5 * 1024 * 1024)
            with tempfile.TemporaryDirectory(prefix="apeir-remote-skill-") as temporary:
                archive = Path(temporary) / "package.zip"
                archive.write_bytes(content)
                with file_lock(self.state_path.with_suffix(".lock")):
                    try:
                        return self.install(
                            archive, expected=entry, before_publish=revalidate
                        )
                    except zipfile.BadZipFile as exc:
                        raise ValueError(
                            "Remote Skill package is not a valid ZIP"
                        ) from exc
        if "://" in entry.source:
            raise ValueError("Remote packages require a registered remote catalog")
        catalog_path = Path(catalog_source).expanduser().resolve()
        base = catalog_path if catalog_path.is_dir() else catalog_path.parent
        source = Path(entry.source).expanduser()
        source = (
            (base / source).resolve() if not source.is_absolute() else source.resolve()
        )
        if not source.is_relative_to(base):
            raise PermissionError(
                "Skill source escapes its registered catalog directory"
            )
        return self.install(source, expected=entry, before_publish=before_publish)

    def update(self, source: str | Path) -> SkillRecord:
        candidate = ExtensionInspector().inspect(source)
        self._require_skill_manifest(candidate)
        skill_id = candidate.skills[0].name
        try:
            current = self.resolve(f"installed:{skill_id}", include_disabled=True)
        except KeyError as exc:
            raise ValueError(f"skill is not installed: {skill_id}") from exc
        previous_artifact = current.artifact_ref
        updated = self.install(source)
        if previous_artifact and previous_artifact != updated.artifact_ref:
            ContentAddressedArtifactStore(self.artifact_root).unpin(previous_artifact)
        return updated

    def remove(
        self,
        skill_id: str,
        *,
        expected_digest: str = "",
        expected_version: str = "",
        before_publish: Callable[[], None] | None = None,
    ) -> bool:
        with file_lock(self.state_path.with_suffix(".lock")):
            return self._remove(
                skill_id,
                expected_digest=expected_digest,
                expected_version=expected_version,
                before_publish=before_publish,
            )

    def _remove(
        self,
        skill_id: str,
        *,
        expected_digest: str,
        expected_version: str,
        before_publish: Callable[[], None] | None,
    ) -> bool:
        requested = str(skill_id or "").split(":", 1)[-1]
        try:
            record = self.resolve(f"installed:{requested}", include_disabled=True)
        except KeyError as exc:
            raise ValueError("only installed skills can be removed") from exc
        if (expected_digest and expected_digest != record.digest) or (
            expected_version and expected_version != record.version
        ):
            raise PermissionError("Skill content changed; review it again")
        extension_id = str(record.metadata.get("extension_id") or "")
        removed = self.extensions.remove(
            extension_id,
            expected_digest=record.digest,
            expected_version=record.version,
            expected_skill_id=record.skill_id,
            before_remove=before_publish,
        )
        if not removed:
            return False
        state = self._state()
        artifact_ref = (
            str(state.setdefault("installed_artifacts", {}).pop(extension_id, ""))
            or record.artifact_ref
        )
        state.setdefault("enabled", {}).pop(record.skill_id, None)
        self._write_state(state)
        if artifact_ref:
            ContentAddressedArtifactStore(self.artifact_root).unpin(artifact_ref)
        return True

    def enable(
        self,
        skill_id: str,
        *,
        expected_digest: str = "",
        expected_version: str = "",
        expected_extension_id: str = "",
        before_publish: Callable[[], None] | None = None,
    ) -> SkillRecord:
        return self._set_enabled(
            skill_id,
            True,
            expected_digest=expected_digest,
            expected_version=expected_version,
            expected_extension_id=expected_extension_id,
            before_publish=before_publish,
        )

    def disable(
        self,
        skill_id: str,
        *,
        expected_digest: str = "",
        expected_version: str = "",
        expected_extension_id: str = "",
        before_publish: Callable[[], None] | None = None,
    ) -> SkillRecord:
        return self._set_enabled(
            skill_id,
            False,
            expected_digest=expected_digest,
            expected_version=expected_version,
            expected_extension_id=expected_extension_id,
            before_publish=before_publish,
        )

    def add_catalog(
        self,
        source: str,
        *,
        before_publish: Callable[[], None] | None = None,
        authorize_remote: Callable[[str], None] | None = None,
    ) -> None:
        source = str(source or "")
        if "://" not in source:
            source = source.strip()
        if not source:
            raise ValueError("catalog source is required")
        remote = "://" in source
        if remote:
            require_remote_url(source)
            self._require_remote_authority(before_publish, authorize_remote)
            assert before_publish is not None and authorize_remote is not None
            before_publish()
            authorize_remote(source)
        catalog = self._read_catalog(source, allow_remote=remote)
        if remote:
            self._validate_remote_entries(catalog, source)
        with file_lock(self.state_path.with_suffix(".lock")):
            state = self._state()
            catalogs = state.setdefault("catalogs", [])
            if source not in catalogs:
                if len(catalogs) >= 32:
                    raise ValueError("Skill Registry exceeds 32 catalogs")
                if remote:
                    before_publish()
                    authorize_remote(source)
                    state.setdefault("catalog_snapshots", {})[source] = catalog
                catalogs.append(source)
                self._write_state(state)

    def remove_catalog(
        self, source: str, *, before_publish: Callable[[], None] | None = None
    ) -> bool:
        with file_lock(self.state_path.with_suffix(".lock")):
            state = self._state()
            catalogs = state.setdefault("catalogs", [])
            if source not in catalogs:
                return False
            if before_publish is not None:
                before_publish()
            catalogs.remove(source)
            state.setdefault("catalog_snapshots", {}).pop(source, None)
            self._write_state(state)
            return True

    def catalogs(self) -> tuple[str, ...]:
        return tuple(str(item) for item in self._state().get("catalogs") or ())

    def _effective(self, include_disabled: bool) -> dict[str, SkillRecord]:
        selected: dict[str, SkillRecord] = {}
        ambiguous: set[str] = set()
        for record in self.list(include_disabled=include_disabled):
            current = selected.get(record.skill_id)
            if current is None or _PROVIDER_PRIORITY.get(
                record.provider, 0
            ) > _PROVIDER_PRIORITY.get(current.provider, 0):
                selected[record.skill_id] = record
            elif record.provider == current.provider == "installed":
                ambiguous.add(record.skill_id)
        for skill_id in ambiguous:
            selected.pop(skill_id, None)
            self.diagnostics.append(
                {
                    "provider": "installed",
                    "source": skill_id,
                    "error": "Installed Skill identity is ambiguous; review its imports",
                }
            )
        return dict(sorted(selected.items()))

    def _local_records(self) -> list[SkillRecord]:
        records: list[SkillRecord] = []
        for provider, root in (
            ("builtin", self.builtin_dir),
            ("user", self.user_dir),
            ("project", self.project_dir),
        ):
            for source in _skill_sources(root):
                try:
                    manifest = ExtensionInspector().inspect(source)
                    self._require_skill_manifest(manifest)
                    records.append(
                        self._record(manifest, provider=provider, source=source)
                    )
                except (OSError, ValueError) as exc:
                    self.diagnostics.append(
                        {"provider": provider, "source": str(source), "error": str(exc)}
                    )
        return records

    def _installed_records(self) -> list[SkillRecord]:
        records: list[SkillRecord] = []
        state = self._state()
        artifacts = state.get("installed_artifacts") or {}
        for item in self.extensions.list():
            extension_id = str(item.get("extension_id") or "")
            try:
                if item.get("state") == "revoked":
                    raise ValueError("Installed Skill Extension has been revoked")
                manifest = self.extensions.verify(extension_id)
                if "skill" not in manifest.kinds:
                    continue
                record = self._record(
                    manifest,
                    provider="installed",
                    source=self.extensions.package_path(extension_id),
                )
                artifact_ref = str(
                    item.get("artifact_ref") or artifacts.get(extension_id) or ""
                )
                if artifact_ref and not ContentAddressedArtifactStore(
                    self.artifact_root
                ).verify(artifact_ref):
                    raise ValueError("Installed Skill Artifact integrity check failed")
                records.append(
                    replace(
                        record,
                        installed=True,
                        artifact_ref=artifact_ref,
                        trust=(
                            "verified"
                            if item.get("signature_status") == "Verified"
                            else "unverified"
                        ),
                    )
                )
            except (OSError, ValueError) as exc:
                self.diagnostics.append(
                    {"provider": "installed", "source": extension_id, "error": str(exc)}
                )
        return records

    def _catalog_records(self, *, local_only: bool = False) -> list[SkillRecord]:
        records: list[SkillRecord] = []
        for source in self.catalogs():
            try:
                catalog = self._read_catalog(source)
            except (OSError, ValueError) as exc:
                self.diagnostics.append(
                    {"provider": "catalog", "source": source, "error": str(exc)}
                )
                continue
            for raw in catalog.get("skills") or ():
                if not isinstance(raw, Mapping):
                    continue
                try:
                    records.append(_catalog_record(raw, source))
                except ValueError as exc:
                    self.diagnostics.append(
                        {"provider": "catalog", "source": source, "error": str(exc)}
                    )
        return records

    def _record(
        self,
        manifest: ExtensionManifest,
        *,
        provider: str,
        source: str | Path,
    ) -> SkillRecord:
        self._require_skill_manifest(manifest)
        skill = manifest.skills[0]
        raw = (
            _legacy_metadata(source)
            if manifest.source_format == "nous-json-skill"
            else {}
        )
        capabilities = tuple(
            sorted({item.capability for item in manifest.capabilities})
        )
        tags = tuple(_string_list(raw.get("triggers") or skill.metadata.get("tags")))
        verification = tuple(
            _string_list(
                raw.get("success_criteria") or skill.metadata.get("verification")
            )
        )
        display_name = str(raw.get("name") or skill.name)
        assert manifest.provenance is not None
        return SkillRecord(
            skill_id=skill.name,
            name=display_name,
            description=skill.description,
            version=manifest.version,
            provider=provider,
            source=str(source),
            source_format=manifest.source_format,
            digest=manifest.provenance.digest,
            requested_capabilities=capabilities,
            suggested_tools=tuple(skill.allowed_tools),
            tags=tags,
            risk=str(skill.metadata.get("risk") or "unknown"),
            verification=verification,
            instructions=skill.instructions,
            resources=tuple(skill.resources),
            trust="builtin" if provider == "builtin" else "unverified",
            metadata={
                **dict(skill.metadata),
                "authority": "none",
                "extension_id": manifest.extension_id,
                "license": skill.license,
                "compatibility": skill.compatibility,
            },
        )

    def _apply_state(self, record: SkillRecord) -> SkillRecord:
        enabled = self._state().get("enabled") or {}
        return replace(record, enabled=bool(enabled.get(record.skill_id, True)))

    def _set_enabled(
        self,
        skill_id: str,
        enabled: bool,
        *,
        expected_digest: str,
        expected_version: str,
        expected_extension_id: str,
        before_publish: Callable[[], None] | None,
    ) -> SkillRecord:
        with file_lock(self.state_path.with_suffix(".lock")):
            record = self.resolve(skill_id, include_disabled=True)
            # Use the existing state -> Extension writer order, shared with
            # installed package removal/acquisition. The reviewed installed
            # version cannot be replaced or revoked by another Registry writer
            # between verification and enabled-state publication.
            fence = (
                self.extensions._writer_lock()
                if record.provider == "installed"
                else nullcontext()
            )
            with fence:
                record = self.resolve(skill_id, include_disabled=True)
                self._require_reviewed_record(
                    record,
                    expected_digest,
                    expected_version,
                    expected_extension_id,
                )
                if before_publish is not None:
                    before_publish()
                # Trusted same-thread callbacks may update Registry state.
                # Reload rather than overwriting their current publication.
                record = self.resolve(skill_id, include_disabled=True)
                self._require_reviewed_record(
                    record,
                    expected_digest,
                    expected_version,
                    expected_extension_id,
                )
                if before_publish is not None:
                    before_publish()
                state = self._state()
                state.setdefault("enabled", {})[record.skill_id] = enabled
                self._write_state(state)
        return replace(record, enabled=enabled)

    @staticmethod
    def _require_reviewed_record(
        record: SkillRecord,
        expected_digest: str,
        expected_version: str,
        expected_extension_id: str,
    ) -> None:
        if (
            (expected_digest and record.digest != expected_digest)
            or (expected_version and record.version != expected_version)
            or (
                expected_extension_id
                and record.metadata.get("extension_id") != expected_extension_id
            )
        ):
            raise PermissionError("Skill content changed; review it again")

    def _read_catalog(
        self, source: str, *, allow_remote: bool = False
    ) -> dict[str, Any]:
        if "://" in source and not allow_remote:
            snapshot = (self._state().get("catalog_snapshots") or {}).get(source)
            if not isinstance(snapshot, dict):
                raise ValueError("Remote catalog requires explicit authorized refresh")
            return self._validate_catalog(snapshot)
        if "://" in source:
            text = self._remote_bytes(source, max_bytes=_MAX_CATALOG_BYTES).decode(
                "utf-8"
            )
        else:
            path = Path(source).expanduser().resolve()
            if path.is_dir():
                return _directory_catalog(path)
            if not path.is_file():
                raise ValueError("skill catalog must be a regular file or directory")
            with path.open("rb") as stream:
                content = stream.read(_MAX_CATALOG_BYTES + 1)
            if len(content) > _MAX_CATALOG_BYTES:
                raise ValueError("skill catalog exceeds 1048576 bytes")
            text = content.decode("utf-8")
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("skill catalog must be valid JSON") from exc
        return self._validate_catalog(value)

    @staticmethod
    def _validate_catalog(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict) or value.get("schema") != _CATALOG_SCHEMA:
            raise ValueError(f"skill catalog schema must be {_CATALOG_SCHEMA}")
        if not isinstance(value.get("skills"), list):
            raise ValueError("skill catalog skills must be an array")
        if len(value["skills"]) > _MAX_CATALOG_SKILLS:
            raise ValueError("skill catalog exceeds 512 entries")
        return value

    def refresh_catalog(
        self,
        source: str,
        *,
        before_publish: Callable[[], None],
        authorize_remote: Callable[[str], None],
    ) -> list[SkillRecord]:
        """Explicitly acquire metadata under the original human URL permission."""
        if source not in self.catalogs():
            raise PermissionError(
                "Catalog must first be registered by the workspace owner"
            )
        require_remote_url(source)
        self._require_remote_authority(before_publish, authorize_remote)
        before_publish()
        authorize_remote(source)
        catalog = self._read_catalog(source, allow_remote=True)
        self._validate_remote_entries(catalog, source)
        with file_lock(self.state_path.with_suffix(".lock")):
            state = self._state()
            if source not in state.get("catalogs", []):
                raise PermissionError("Skill catalog was removed during acquisition")
            before_publish()
            authorize_remote(source)
            state.setdefault("catalog_snapshots", {})[source] = catalog
            self._write_state(state)
        return [_catalog_record(raw, source) for raw in catalog["skills"]]

    @staticmethod
    def _validate_remote_entries(catalog: dict[str, Any], source: str) -> None:
        seen: set[str] = set()
        for raw in catalog["skills"]:
            if not isinstance(raw, Mapping):
                raise ValueError("Remote catalog Skill entries must be objects")
            entry = _catalog_record(raw, source)
            require_remote_url(entry.source)
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", entry.digest):
                raise ValueError(
                    "Remote catalog Skills require exact SHA-256 package digests"
                )
            if entry.skill_id in seen:
                raise ValueError("Remote catalog contains ambiguous Skill entries")
            seen.add(entry.skill_id)

    @staticmethod
    def _require_remote_authority(before_publish, authorize_remote) -> None:
        if not callable(before_publish) or not callable(authorize_remote):
            raise PermissionError(
                "Remote Skills require trusted human and exact source permission callbacks"
            )

    @staticmethod
    def _remote_bytes(source: str, *, max_bytes: int) -> bytes:
        from nous_runtime.skills.remote import RemoteSkillGateway

        return RemoteSkillGateway().fetch_bytes(source, max_bytes=max_bytes)

    def _state(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            return {
                "schema": _STATE_SCHEMA,
                "enabled": {},
                "installed_artifacts": {},
                "catalogs": [],
            }
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Skill Registry state is invalid") from exc
        if not isinstance(value, dict) or value.get("schema") != _STATE_SCHEMA:
            raise ValueError("Skill Registry state schema is invalid")
        return value

    def _write_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.state_path)

    @staticmethod
    def _require_skill_manifest(manifest: ExtensionManifest) -> None:
        if "skill" not in manifest.kinds or len(manifest.skills) != 1:
            raise ValueError("Skill Registry accepts exactly one normalized Skill")


def _skill_sources(root: Path) -> tuple[Path, ...]:
    if not root.is_dir():
        return ()
    sources: list[Path] = []
    if (root / "SKILL.md").is_file():
        sources.append(root)
    sources.extend(sorted(root.glob("*.json")))
    sources.extend(
        item
        for item in sorted(root.iterdir())
        if item.is_dir() and (item / "SKILL.md").is_file()
    )
    return tuple(dict.fromkeys(sources))


def _legacy_metadata(source: str | Path) -> dict[str, Any]:
    path = Path(source)
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError:
                value = [item.strip() for item in stripped.split(",")]
        else:
            value = [item.strip() for item in stripped.split(",")]
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _deterministic_bundle(root: Path) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in package_files(root):
            relative = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    return output.getvalue()


def _directory_catalog(root: Path) -> dict[str, Any]:
    skills: list[dict[str, Any]] = []
    inspector = ExtensionInspector()
    for source in _skill_sources(root):
        if len(skills) >= _MAX_CATALOG_SKILLS:
            raise ValueError("skill catalog exceeds 512 entries")
        manifest = inspector.inspect(source)
        if "skill" not in manifest.kinds or len(manifest.skills) != 1:
            continue
        skill = manifest.skills[0]
        assert manifest.provenance is not None
        skills.append(
            {
                "name": skill.name,
                "description": skill.description,
                "version": manifest.version,
                "source": str(source),
                "digest": manifest.provenance.digest,
                "requested_capabilities": sorted(
                    {item.capability for item in manifest.capabilities}
                ),
                "suggested_tools": list(skill.allowed_tools),
                "tags": _string_list(skill.metadata.get("tags")),
                "risk": str(skill.metadata.get("risk") or "unknown"),
                "compatibility": skill.compatibility,
            }
        )
    return {"schema": _CATALOG_SCHEMA, "skills": skills}


def _catalog_record(raw: Mapping[str, Any], catalog_source: str) -> SkillRecord:
    skill_id = str(raw.get("name") or raw.get("skill_id") or "").strip()
    description = str(raw.get("description") or "").strip()
    version = str(raw.get("version") or "").strip()
    digest = str(raw.get("digest") or "").strip()
    if not skill_id or not description or not version:
        raise ValueError("catalog skill requires name, description, and version")
    return SkillRecord(
        skill_id=skill_id,
        name=str(raw.get("display_name") or skill_id),
        description=description,
        version=version,
        provider="catalog",
        source=str(raw.get("source") or catalog_source),
        source_format="skill-catalog",
        digest=digest,
        requested_capabilities=tuple(_string_list(raw.get("requested_capabilities"))),
        suggested_tools=tuple(_string_list(raw.get("suggested_tools"))),
        tags=tuple(_string_list(raw.get("tags"))),
        risk=str(raw.get("risk") or "unknown"),
        trust="unverified",
        metadata={
            "authority": "none",
            "catalog_source": catalog_source,
            "compatibility": str(raw.get("compatibility") or "unspecified"),
            "dependencies": _string_list(raw.get("dependencies")),
        },
    )


__all__ = ["SkillRegistry"]

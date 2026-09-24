"""Unified Skill discovery and installation over existing Runtime mechanisms."""

from __future__ import annotations

import io
import json
import os
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from nous_runtime.artifact.content_store import ContentAddressedArtifactStore
from nous_runtime.artifact.models import ArtifactType
from nous_runtime.extensions import ExtensionInspector, ExtensionRegistry
from nous_runtime.extensions.models import ExtensionManifest
from nous_runtime.extensions.sources import package_files
from nous_runtime.skills.models import SkillRecord


_STATE_SCHEMA = "apeir.skill-registry-state/v1"
_CATALOG_SCHEMA = "apeir.skill-catalog/v1"
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

    def list(self, *, include_disabled: bool = False) -> list[SkillRecord]:
        records = self._local_records()
        records.extend(self._installed_records())
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
        return max(matches, key=lambda item: _PROVIDER_PRIORITY.get(item.provider, 0))

    def load(self, skill_id: str) -> SkillRecord:
        """Load full instructions and resource names without executing resources."""

        record = self.resolve(skill_id)
        if record.provider == "catalog":
            raise ValueError("catalog skills must be installed before loading")
        return record

    def install(self, source: str | Path) -> SkillRecord:
        """Inspect, copy, evidence, and register a Skill without executing scripts."""

        manifest = ExtensionInspector().inspect(source)
        self._require_skill_manifest(manifest)
        installed = self.extensions.install(source)
        assert installed.provenance is not None
        package_root = self.extensions.package_path(installed.extension_id)
        bundle = _deterministic_bundle(package_root)
        artifact = ContentAddressedArtifactStore(self.artifact_root).store_bytes(
            bundle,
            artifact_type=ArtifactType.SOURCE_BUNDLE,
            name=f"{installed.skills[0].name}-{installed.version}.skill.zip",
            media_type="application/vnd.apeir.skill-bundle+zip",
            produced_by="apeir.skill-registry",
            metadata={
                "extension_id": installed.extension_id,
                "skill_id": installed.skills[0].name,
                "version": installed.version,
                "package_digest": installed.provenance.digest,
                "authority": "none",
            },
        )
        artifact_ref = str(artifact["artifact"]["digest"])
        store = ContentAddressedArtifactStore(self.artifact_root)
        store.pin(artifact_ref, reason=f"installed-skill:{installed.extension_id}")
        state = self._state()
        state.setdefault("installed_artifacts", {})[installed.extension_id] = (
            artifact_ref
        )
        state.setdefault("enabled", {})[installed.skills[0].name] = True
        self._write_state(state)
        return self.resolve(f"installed:{installed.skills[0].name}")

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

    def remove(self, skill_id: str) -> bool:
        requested = str(skill_id or "").split(":", 1)[-1]
        try:
            record = self.resolve(f"installed:{requested}", include_disabled=True)
        except KeyError as exc:
            raise ValueError("only installed skills can be removed") from exc
        extension_id = str(record.metadata.get("extension_id") or "")
        removed = self.extensions.remove(extension_id)
        if not removed:
            return False
        state = self._state()
        artifact_ref = str(
            state.setdefault("installed_artifacts", {}).pop(extension_id, "")
        )
        state.setdefault("enabled", {}).pop(record.skill_id, None)
        self._write_state(state)
        if artifact_ref:
            ContentAddressedArtifactStore(self.artifact_root).unpin(artifact_ref)
        return True

    def enable(self, skill_id: str) -> SkillRecord:
        return self._set_enabled(skill_id, True)

    def disable(self, skill_id: str) -> SkillRecord:
        return self._set_enabled(skill_id, False)

    def add_catalog(self, source: str) -> None:
        source = str(source or "").strip()
        if not source:
            raise ValueError("catalog source is required")
        self._read_catalog(source)
        state = self._state()
        catalogs = state.setdefault("catalogs", [])
        if source not in catalogs:
            catalogs.append(source)
            self._write_state(state)

    def remove_catalog(self, source: str) -> bool:
        state = self._state()
        catalogs = state.setdefault("catalogs", [])
        if source not in catalogs:
            return False
        catalogs.remove(source)
        self._write_state(state)
        return True

    def catalogs(self) -> tuple[str, ...]:
        return tuple(str(item) for item in self._state().get("catalogs") or ())

    def _effective(self, include_disabled: bool) -> dict[str, SkillRecord]:
        selected: dict[str, SkillRecord] = {}
        for record in self.list(include_disabled=include_disabled):
            current = selected.get(record.skill_id)
            if current is None or _PROVIDER_PRIORITY.get(
                record.provider, 0
            ) > _PROVIDER_PRIORITY.get(current.provider, 0):
                selected[record.skill_id] = record
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
                manifest = self.extensions.verify(extension_id)
                if "skill" not in manifest.kinds:
                    continue
                record = self._record(
                    manifest,
                    provider="installed",
                    source=self.extensions.package_path(extension_id),
                )
                records.append(
                    replace(
                        record,
                        installed=True,
                        artifact_ref=str(artifacts.get(extension_id) or ""),
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

    def _catalog_records(self) -> list[SkillRecord]:
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
                "authority": "none",
                "extension_id": manifest.extension_id,
                "license": skill.license,
                "compatibility": skill.compatibility,
                **dict(skill.metadata),
            },
        )

    def _apply_state(self, record: SkillRecord) -> SkillRecord:
        enabled = self._state().get("enabled") or {}
        return replace(record, enabled=bool(enabled.get(record.skill_id, True)))

    def _set_enabled(self, skill_id: str, enabled: bool) -> SkillRecord:
        record = self.resolve(skill_id, include_disabled=True)
        state = self._state()
        state.setdefault("enabled", {})[record.skill_id] = enabled
        self._write_state(state)
        return replace(record, enabled=enabled)

    def _read_catalog(self, source: str) -> dict[str, Any]:
        if source.startswith("https://"):
            from nous_runtime.evidence.web_gateway import WebGateway, WebRequest

            response = WebGateway().fetch(
                WebRequest(
                    url=source,
                    method="GET",
                    timeout_seconds=30,
                    max_size_bytes=1024 * 1024,
                    approval_requirement="not_required",
                )
            )
            if not response.ok:
                raise ValueError(response.error_message or "catalog fetch failed")
            text = response.content
        else:
            path = Path(source).expanduser().resolve()
            if path.is_dir():
                return _directory_catalog(path)
            text = path.read_text(encoding="utf-8")
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("skill catalog must be valid JSON") from exc
        if not isinstance(value, dict) or value.get("schema") != _CATALOG_SCHEMA:
            raise ValueError(f"skill catalog schema must be {_CATALOG_SCHEMA}")
        if not isinstance(value.get("skills"), list):
            raise ValueError("skill catalog skills must be an array")
        return value

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
        trust=str(raw.get("trust") or "unverified"),
        metadata={"authority": "none", "catalog_source": catalog_source},
    )


__all__ = ["SkillRegistry"]

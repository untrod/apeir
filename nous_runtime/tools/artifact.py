"""Tool adapter over the existing workspace ContentAddressedArtifactStore."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Mapping

from nous_runtime.agents.adapters.workspace_guard import WorkspaceGuard
from nous_runtime.artifact.content_store import ContentAddressedArtifactStore
from nous_runtime.artifact.models import ArtifactType
from nous_runtime.core.errors import ArtifactError


_MAX_GET_BYTES = 1024 * 1024


class ArtifactToolRuntime:
    """Expose Artifact Runtime operations without creating another store."""

    def __init__(
        self,
        workspace: str | Path,
        *,
        allow_mutations: bool = False,
    ) -> None:
        self.guard = WorkspaceGuard(str(workspace))
        self.root = Path(self.guard.root)
        self._artifact_store: ContentAddressedArtifactStore | None = None
        self.allow_mutations = bool(allow_mutations)

    def specifications(self) -> tuple[dict[str, Any], ...]:
        digest = {
            "type": "string",
            "pattern": "^sha256:[0-9a-f]{64}$",
        }
        specs = [
            _tool(
                "artifact_list",
                "List immutable artifacts in the workspace Artifact Runtime.",
                {
                    "artifact_type": {
                        "type": "string",
                        "enum": [item.value for item in ArtifactType],
                    }
                },
            ),
            _tool(
                "artifact_inspect",
                "Inspect and integrity-check one immutable artifact.",
                {"digest": digest},
                required=("digest",),
            ),
            _tool(
                "artifact_get",
                "Read up to 1 MiB from a verified immutable artifact.",
                {"digest": digest},
                required=("digest",),
            ),
        ]
        if self.allow_mutations:
            specs.append(
                _tool(
                    "artifact_put",
                    "Store one workspace file as an immutable content-addressed artifact.",
                    {
                        "path": {"type": "string", "minLength": 1},
                        "artifact_type": {
                            "type": "string",
                            "enum": [item.value for item in ArtifactType],
                        },
                        "name": {"type": "string"},
                        "media_type": {"type": "string"},
                    },
                    required=("path", "artifact_type"),
                )
            )
        return tuple(specs)

    def execute(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        handlers = {
            "artifact_list": self._list,
            "artifact_inspect": self._inspect,
            "artifact_get": self._get,
            "artifact_put": self._put,
        }
        handler = handlers.get(str(name or ""))
        if handler is None:
            return {"ok": False, "error": f"unknown Artifact tool: {name}"}
        if name == "artifact_put" and not self.allow_mutations:
            return {
                "ok": False,
                "error": "artifact mutation requires an explicit user request",
            }
        try:
            return handler(dict(arguments))
        except (ArtifactError, OSError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    def _list(self, arguments: dict[str, Any]) -> dict[str, Any]:
        artifact_type = str(arguments.get("artifact_type") or "")
        return {
            "ok": True,
            "artifacts": [
                item.to_dict() for item in self._store().list(artifact_type or None)
            ],
        }

    def _inspect(self, arguments: dict[str, Any]) -> dict[str, Any]:
        digest = str(arguments.get("digest") or "")
        store = self._store()
        record = store.get(digest)
        if record is None:
            return {"ok": False, "error": f"artifact not found: {digest}"}
        verified = store.verify(digest)
        return {
            "ok": verified,
            "artifact": record.to_dict(),
            "integrity": "verified" if verified else "invalid",
        }

    def _get(self, arguments: dict[str, Any]) -> dict[str, Any]:
        digest = str(arguments.get("digest") or "")
        store = self._store()
        record = store.get(digest)
        if record is None:
            return {"ok": False, "error": f"artifact not found: {digest}"}
        path = store.resolve(digest, verify=True)
        if record.size_bytes > _MAX_GET_BYTES:
            return {"ok": False, "error": "artifact exceeds the 1 MiB tool read limit"}
        content = path.read_bytes()
        return {
            "ok": True,
            "artifact": record.to_dict(),
            "content_base64": base64.b64encode(content).decode("ascii"),
        }

    def _put(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = Path(
            self.guard.validate_path(
                str(arguments.get("path") or ""),
                allow_nonexistent=False,
            )
        )
        relative = path.relative_to(self.root)
        if not path.is_file():
            raise ValueError("artifact source must be a workspace file")
        if relative.parts and relative.parts[0] == ".nous":
            raise ValueError("Nous internal files cannot be imported as user artifacts")
        result = self._store().store_file(
            path,
            artifact_type=str(arguments.get("artifact_type") or ""),
            name=str(arguments.get("name") or path.name),
            media_type=str(arguments.get("media_type") or "application/octet-stream"),
            produced_by="nous.work.tool-catalog",
            metadata={"workspace_path": relative.as_posix()},
        )
        return {"ok": True, **result}

    def _store(self) -> ContentAddressedArtifactStore:
        if self._artifact_store is None:
            self._artifact_store = ContentAddressedArtifactStore(
                self.root / ".nous" / "artifacts"
            )
        return self._artifact_store


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    *,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(required),
                "additionalProperties": False,
            },
        },
    }


__all__ = ["ArtifactToolRuntime"]

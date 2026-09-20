"""
Automatic workspace creation for desktop first-run experience.

Creates a default workspace structure at a user-writable location,
with proper directory layout and a workspace.json manifest.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nous_runtime.schema_registry import WORKSPACE_SCHEMA_VERSION

log = logging.getLogger("nous.workspace.auto_create")

DEFAULT_WORKSPACE_NAME = "NousWorkspace"

WORKSPACE_DIRS = [
    "artifacts",
    "conversations",
    "tasks",
    "knowledge",
    "logs",
    "cache",
    "exports",
    "checkpoints",
]


def _default_workspace_root() -> Path:
    """Return the recommended default workspace root for the current platform."""
    if os.name == "nt":
        userprofile = os.environ.get("USERPROFILE", "")
        if userprofile:
            return Path(userprofile) / DEFAULT_WORKSPACE_NAME
        localappdata = os.environ.get("LOCALAPPDATA", "")
        if localappdata:
            return Path(localappdata) / "Nous" / "workspace"
        return Path.home() / DEFAULT_WORKSPACE_NAME
    else:
        return Path.home() / DEFAULT_WORKSPACE_NAME


def _is_safe_location(path: Path) -> bool:
    """Reject roots and protected locations before any workspace write."""
    unsafe_prefixes = []
    if os.name == "nt":
        program_files = os.environ.get("ProgramFiles", "")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", "")
        system_root = os.environ.get("SystemRoot", "")
        if program_files:
            unsafe_prefixes.append(Path(program_files))
        if program_files_x86:
            unsafe_prefixes.append(Path(program_files_x86))
        if system_root:
            unsafe_prefixes.append(Path(system_root))
    else:
        unsafe_prefixes.extend(
            [Path("/usr"), Path("/bin"), Path("/sbin"), Path("/etc"), Path("/opt")]
        )

    resolved = path.resolve()
    if resolved.parent == resolved or resolved == Path.home().resolve():
        return False

    if os.name == "nt":
        localappdata = os.environ.get("LOCALAPPDATA", "")
        if localappdata:
            unsafe_prefixes.append(Path(localappdata) / "Nous")

    for prefix in unsafe_prefixes:
        try:
            resolved.relative_to(prefix)
            return False
        except ValueError:
            pass
    return True


def workspace_manifest(
    workspace_root: Path,
    display_name: str = DEFAULT_WORKSPACE_NAME,
) -> dict[str, Any]:
    """Create a workspace.json manifest with non-sensitive metadata."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": WORKSPACE_SCHEMA_VERSION,
        "workspace_id": str(uuid.uuid4()),
        "display_name": display_name,
        "created_at": now,
        "updated_at": now,
        "runtime_version": "",
        "default_language": "zh-CN",
        "default_provider": "",
        "default_model": "",
        "artifact_directory": str(workspace_root / "artifacts"),
        "knowledge_directory": str(workspace_root / "knowledge"),
    }


def _ensure_workspace_registry(
    root: Path,
    manifest: dict[str, Any],
) -> None:
    """Persist the Runtime-owned active workspace registry atomically."""
    workspace_id = str(manifest.get("workspace_id") or "").strip()
    if not workspace_id:
        raise ValueError("workspace manifest has no workspace_id")
    display_name = str(
        manifest.get("display_name") or root.name or DEFAULT_WORKSPACE_NAME
    )

    registry_path = root / ".nous" / "workspaces.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    if registry_path.exists():
        raw = json.loads(registry_path.read_text(encoding="utf-8") or "{}")
        if not isinstance(raw, dict):
            raise ValueError("workspace registry must be an object")
        registry = raw
    else:
        registry = {"active_workspace": "", "workspaces": []}

    workspaces = registry.get("workspaces")
    if not isinstance(workspaces, list):
        raise ValueError("workspace registry workspaces must be a list")
    entry = {
        "id": workspace_id,
        "name": display_name,
        "owner": "local",
        "type": "project",
        "permissions": ["read", "write"],
        "context_policy": "workspace_only",
        "memory_policy": "workspace_only",
        "active_project": "",
        "path": str(root.resolve()),
        "created_at": str(manifest.get("created_at") or ""),
        "metadata": {"managed_by": "nous-runtime"},
    }
    for index, existing in enumerate(workspaces):
        if isinstance(existing, dict) and str(existing.get("id") or "") == workspace_id:
            workspaces[index] = entry
            break
    else:
        workspaces.append(entry)
    registry["active_workspace"] = workspace_id
    registry["workspaces"] = workspaces

    temporary = registry_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(registry_path)


def create_default_workspace(root: str | Path | None = None) -> dict[str, Any]:
    """
    Create a default workspace with all required directories and manifest.

    Returns a dict with status and path information.
    Never overwrites an existing workspace.
    """
    if root is None:
        root = _default_workspace_root()
    else:
        root = Path(root)

    # Safety checks
    if not _is_safe_location(root):
        return {
            "ok": False,
            "error": "NOUS_UNSAFE_LOCATION",
            "message": (
                f"Workspace path '{root}' is inside a protected system directory. "
                "Please choose a location under your user profile."
            ),
            "path": str(root),
        }

    # Check if already exists
    workspace_json = root / "workspace.json"
    if workspace_json.exists():
        try:
            with open(workspace_json, "r", encoding="utf-8") as f:
                existing = json.load(f)
            _ensure_workspace_registry(root, existing)
            log.info("Workspace already exists at %s", root)
            return {
                "ok": True,
                "created": False,
                "path": str(root),
                "workspace_id": existing.get("workspace_id", ""),
                "message": "Workspace already exists",
            }
        except (json.JSONDecodeError, OSError, ValueError):
            # Corrupted manifest — will be recreated
            log.warning(
                "Workspace manifest at %s is corrupted, recreating", workspace_json
            )

    # Check write permissions
    try:
        root.mkdir(parents=True, exist_ok=True)
        test_file = root / ".write_test"
        test_file.touch()
        test_file.unlink()
    except (OSError, PermissionError) as e:
        return {
            "ok": False,
            "error": "NOUS_PERMISSION_DENIED",
            "message": (
                f"Cannot write to workspace path '{root}'. "
                f"Error: {e}. Check file permissions or choose a different location."
            ),
            "path": str(root),
        }

    # Create directories
    created_dirs = []
    for dirname in WORKSPACE_DIRS:
        dirpath = root / dirname
        try:
            dirpath.mkdir(parents=True, exist_ok=True)
            created_dirs.append(str(dirpath))
        except OSError as e:
            log.error("Failed to create workspace directory %s: %s", dirpath, e)
            return {
                "ok": False,
                "error": "NOUS_DIRECTORY_CREATE_FAILED",
                "message": f"Failed to create '{dirpath}': {e}",
                "path": str(root),
                "created_dirs": created_dirs,
            }

    # Write manifest
    manifest = workspace_manifest(root)
    manifest_path = root / "workspace.json"
    try:
        # Atomic write: write to temp, then rename
        tmp_path = manifest_path.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        tmp_path.replace(manifest_path)
    except OSError as e:
        log.error("Failed to write workspace manifest: %s", e)
        return {
            "ok": False,
            "error": "NOUS_MANIFEST_WRITE_FAILED",
            "message": f"Failed to write workspace.json: {e}",
            "path": str(root),
        }

    try:
        _ensure_workspace_registry(root, manifest)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        log.error("Failed to write workspace registry: %s", error)
        return {
            "ok": False,
            "error": "NOUS_REGISTRY_WRITE_FAILED",
            "message": f"Failed to write workspace registry: {error}",
            "path": str(root),
        }

    log.info("Created default workspace at %s", root)
    return {
        "ok": True,
        "created": True,
        "path": str(root),
        "workspace_id": manifest["workspace_id"],
        "directories": created_dirs,
        "message": f"Workspace created at {root}",
    }


def ensure_workspace(workspace_root: str | None = None) -> dict[str, Any]:
    """
    Ensure a workspace exists, creating one if needed.

    This is the main entry point for the desktop bootstrap flow.
    """
    if workspace_root:
        root = Path(workspace_root)
    else:
        root = (
            Path(os.environ.get("NOUS_WORKSPACE_ROOT", ""))
            if os.environ.get("NOUS_WORKSPACE_ROOT")
            else None
        )
        if root is None:
            root = _default_workspace_root()

    # Set env var for consistency
    os.environ["NOUS_WORKSPACE_ROOT"] = str(root)

    return create_default_workspace(root)

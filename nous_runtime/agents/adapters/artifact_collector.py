# -*- coding: utf-8 -*-
"""ArtifactCollector — collects and validates artifacts from agent runs."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from nous_runtime.agents.external.models import AgentArtifact


class ArtifactCollector:
    """Collects declared artifacts from the workspace after a run.

    Artifacts are files the agent declares it will produce.
    The collector:
    - Finds them in the workspace
    - Computes checksums
    - Records metadata
    - Validates they are within workspace boundaries
    """

    def __init__(self, workspace_root: str):
        self._workspace = str(Path(workspace_root).resolve(strict=False))
        self._collected: list[AgentArtifact] = []

    @property
    def collected(self) -> list[AgentArtifact]:
        return list(self._collected)

    def collect(
        self,
        run_id: str,
        expected_artifacts: tuple[str, ...],
    ) -> list[AgentArtifact]:
        """Collect expected artifacts from the workspace.

        Only collects files that were explicitly declared in the run request.
        """
        results: list[AgentArtifact] = []
        for artifact_path in expected_artifacts:
            full_path = os.path.join(self._workspace, artifact_path)
            try:
                resolved = str(Path(full_path).resolve(strict=False))
                if not resolved.startswith(self._workspace):
                    continue
                if not os.path.isfile(resolved):
                    continue
                stat = os.stat(resolved)
                checksum = self._checksum_file(resolved)
                art = AgentArtifact(
                    run_id=run_id,
                    name=artifact_path,
                    path=resolved,
                    size_bytes=stat.st_size,
                    checksum=checksum,
                )
                results.append(art)
            except OSError:
                continue
        self._collected = results
        return results

    def discover_changed_files(
        self, before_snapshot: dict[str, str] | None = None
    ) -> dict[str, str]:
        """Discover files changed during the run by comparing checksums.

        Args:
            before_snapshot: dict of {path: checksum} from before the run
        Returns:
            dict of {path: new_checksum} for changed files
        """
        changed: dict[str, str] = {}
        for root, _dirs, files in os.walk(self._workspace):
            for name in files:
                full = os.path.join(root, name)
                try:
                    rel = os.path.relpath(full, self._workspace)
                    csum = self._checksum_file(full)
                    if before_snapshot is None or before_snapshot.get(rel) != csum:
                        changed[rel] = csum
                except OSError:
                    continue
        return changed

    @staticmethod
    def _checksum_file(path: str) -> str:
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def snapshot_workspace(workspace_root: str) -> dict[str, str]:
        """Create a checksum snapshot of all files in the workspace."""
        snapshot: dict[str, str] = {}
        ws = str(Path(workspace_root).resolve(strict=False))
        if not os.path.isdir(ws):
            return snapshot
        for root, _dirs, files in os.walk(ws):
            for name in files:
                full = os.path.join(root, name)
                try:
                    rel = os.path.relpath(full, ws)
                    hasher = hashlib.sha256()
                    with open(full, "rb") as f:
                        while True:
                            chunk = f.read(65536)
                            if not chunk:
                                break
                            hasher.update(chunk)
                    snapshot[rel] = hasher.hexdigest()
                except OSError:
                    continue
        return snapshot

    def reset(self) -> None:
        self._collected = []

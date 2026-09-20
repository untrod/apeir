# -*- coding: utf-8 -*-
"""Personal Project Assistant — tracks project progress, manages checkpoints,
and provides intelligent project oversight across multiple projects."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger("nous.persona.project")


# Data models

@dataclass
class ProjectMilestone:
    name: str
    description: str = ""
    due_date: str = ""
    completed: bool = False
    completed_at: str = ""


@dataclass
class ProjectCheckpoint:
    id: str = ""
    description: str = ""
    timestamp: str = ""
    file_snapshot: dict[str, str] = field(default_factory=dict)


@dataclass
class Project:
    name: str
    description: str = ""
    repo_path: str = ""
    status: str = "active"  # active, paused, completed
    priority: str = "medium"  # high, medium, low
    created_at: str = ""
    updated_at: str = ""
    milestones: list[ProjectMilestone] = field(default_factory=list)
    checkpoints: list[ProjectCheckpoint] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    notes: str = ""


# Project Assistant

class ProjectAssistant:
    """Manages multiple projects with milestone tracking and checkpoints.

    Features:
    - Multi-project management
    - Milestone tracking with progress indicators
    - Project checkpoints for state preservation
    - Status dashboards
    - Integration with Nous Runtime task/project system
    """

    def __init__(self, workspace: str | Path = ""):
        self._workspace = (
            Path(workspace) if workspace else Path.home() / ".nous"
        )
        self._data_dir = self._workspace / "projects"
        self._projects_path = self._data_dir / "projects.json"
        self._projects: dict[str, Project] = {}
        self._load()

    # Project CRUD

    def create_project(
        self,
        name: str,
        description: str = "",
        repo_path: str = "",
        priority: str = "medium",
        tags: list[str] | None = None,
    ) -> Project:
        """Create a new project."""
        key = self._project_key(name)
        if key in self._projects:
            raise ValueError(f"Project '{name}' already exists")

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        project = Project(
            name=name,
            description=description,
            repo_path=repo_path,
            priority=priority,
            created_at=now,
            updated_at=now,
            tags=tags or [],
        )
        self._projects[key] = project
        self._save()
        _log.info("Project created: %s", name)
        return project

    def get_project(self, name: str) -> Project | None:
        """Get a project by name."""
        return self._projects.get(self._project_key(name))

    def list_projects(
        self, status: str = "", priority: str = "", tag: str = "",
    ) -> list[Project]:
        """List projects with optional filtering."""
        result = list(self._projects.values())
        if status:
            result = [p for p in result if p.status == status]
        if priority:
            result = [p for p in result if p.priority == priority]
        if tag:
            result = [p for p in result if tag in p.tags]
        return sorted(result, key=lambda p: p.updated_at, reverse=True)

    def update_status(
        self, name: str, status: str, notes: str = "",
    ) -> Project | None:
        """Update project status."""
        project = self.get_project(name)
        if not project:
            return None
        project.status = status
        project.updated_at = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        if notes:
            project.notes = notes
        self._save()
        return project

    # Milestones

    def add_milestone(
        self,
        project_name: str,
        milestone_name: str,
        description: str = "",
        due_date: str = "",
    ) -> ProjectMilestone | None:
        """Add a milestone to a project."""
        project = self.get_project(project_name)
        if not project:
            return None
        milestone = ProjectMilestone(
            name=milestone_name,
            description=description,
            due_date=due_date,
        )
        project.milestones.append(milestone)
        project.updated_at = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        self._save()
        return milestone

    def complete_milestone(
        self, project_name: str, milestone_name: str,
    ) -> bool:
        """Mark a milestone as completed."""
        project = self.get_project(project_name)
        if not project:
            return False
        for m in project.milestones:
            if m.name == milestone_name and not m.completed:
                m.completed = True
                m.completed_at = datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                project.updated_at = m.completed_at
                self._save()
                return True
        return False

    # Checkpoints

    def create_checkpoint(
        self,
        project_name: str,
        description: str = "",
        files: dict[str, str] | None = None,
    ) -> ProjectCheckpoint | None:
        """Create a named checkpoint for a project."""
        project = self.get_project(project_name)
        if not project:
            return None

        import uuid
        checkpoint = ProjectCheckpoint(
            id=f"cp_{uuid.uuid4().hex[:12]}",
            description=description,
            timestamp=datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            file_snapshot=files or {},
        )
        project.checkpoints.append(checkpoint)
        project.updated_at = checkpoint.timestamp
        self._save()
        _log.info(
            "Checkpoint created for '%s': %s",
            project_name, checkpoint.id,
        )
        return checkpoint

    def list_checkpoints(
        self, project_name: str,
    ) -> list[ProjectCheckpoint]:
        """List checkpoints for a project."""
        project = self.get_project(project_name)
        return project.checkpoints if project else []

    # Dashboard

    def get_dashboard(self) -> dict[str, Any]:
        """Generate a project dashboard overview."""
        all_projects = list(self._projects.values())
        active = [p for p in all_projects if p.status == "active"]
        paused = [p for p in all_projects if p.status == "paused"]
        completed = [p for p in all_projects if p.status == "completed"]

        total_milestones = sum(
            len(p.milestones) for p in all_projects
        )
        completed_milestones = sum(
            sum(1 for m in p.milestones if m.completed)
            for p in all_projects
        )

        return {
            "projects_total": len(all_projects),
            "projects_active": len(active),
            "projects_paused": len(paused),
            "projects_completed": len(completed),
            "milestones_total": total_milestones,
            "milestones_completed": completed_milestones,
            "milestones_progress_pct": round(
                completed_milestones / max(1, total_milestones) * 100, 1
            ),
            "active_projects": [
                {
                    "name": p.name,
                    "priority": p.priority,
                    "status": p.status,
                    "milestones_done": sum(
                        1 for m in p.milestones if m.completed
                    ),
                    "milestones_total": len(p.milestones),
                    "tags": p.tags,
                }
                for p in active
            ],
        }

    def get_project_summary(self, name: str) -> dict[str, Any] | None:
        """Get a detailed summary of one project."""
        project = self.get_project(name)
        if not project:
            return None

        completed = sum(1 for m in project.milestones if m.completed)
        total = len(project.milestones)

        return {
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "priority": project.priority,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
            "tags": project.tags,
            "milestones_progress": f"{completed}/{total}",
            "milestones_progress_pct": round(
                completed / max(1, total) * 100, 1
            ),
            "milestones": [
                {
                    "name": m.name,
                    "description": m.description,
                    "due_date": m.due_date,
                    "completed": m.completed,
                    "completed_at": m.completed_at,
                }
                for m in project.milestones
            ],
            "checkpoints_count": len(project.checkpoints),
            "last_checkpoint": project.checkpoints[-1].timestamp
            if project.checkpoints
            else None,
            "notes": project.notes,
        }

    # Persistence

    def _project_key(self, name: str) -> str:
        return name.lower().replace(" ", "_")

    def _load(self) -> None:
        """Load projects from disk."""
        try:
            if self._projects_path.is_file():
                data = json.loads(
                    self._projects_path.read_text(encoding="utf-8")
                )
                for k, v in data.get("projects", {}).items():
                    milestones = [
                        ProjectMilestone(
                            name=m.get("name", ""),
                            description=m.get("description", ""),
                            due_date=m.get("due_date", ""),
                            completed=m.get("completed", False),
                            completed_at=m.get("completed_at", ""),
                        )
                        for m in v.get("milestones", [])
                    ]
                    checkpoints = [
                        ProjectCheckpoint(
                            id=c.get("id", ""),
                            description=c.get("description", ""),
                            timestamp=c.get("timestamp", ""),
                            file_snapshot=c.get("file_snapshot", {}),
                        )
                        for c in v.get("checkpoints", [])
                    ]
                    self._projects[k] = Project(
                        name=v.get("name", k),
                        description=v.get("description", ""),
                        repo_path=v.get("repo_path", ""),
                        status=v.get("status", "active"),
                        priority=v.get("priority", "medium"),
                        created_at=v.get("created_at", ""),
                        updated_at=v.get("updated_at", ""),
                        milestones=milestones,
                        checkpoints=checkpoints,
                        tags=v.get("tags", []),
                        notes=v.get("notes", ""),
                    )
        except Exception as exc:
            _log.warning("Could not load projects: %s", exc)

    def _save(self) -> None:
        """Save projects to disk."""
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            data = {
                "projects": {
                    k: {
                        "name": v.name,
                        "description": v.description,
                        "repo_path": v.repo_path,
                        "status": v.status,
                        "priority": v.priority,
                        "created_at": v.created_at,
                        "updated_at": v.updated_at,
                        "milestones": [
                            {
                                "name": m.name,
                                "description": m.description,
                                "due_date": m.due_date,
                                "completed": m.completed,
                                "completed_at": m.completed_at,
                            }
                            for m in v.milestones
                        ],
                        "checkpoints": [
                            {
                                "id": c.id,
                                "description": c.description,
                                "timestamp": c.timestamp,
                                "file_snapshot": c.file_snapshot,
                            }
                            for c in v.checkpoints[-50:]  # Keep last 50
                        ],
                        "tags": v.tags,
                        "notes": v.notes,
                    }
                    for k, v in self._projects.items()
                },
                "updated_at": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            }
            self._projects_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            _log.warning("Could not save projects: %s", exc)


# Convenience functions

def create_project_assistant(
    workspace: str | Path = "",
) -> ProjectAssistant:
    """Create a project assistant for the given workspace."""
    return ProjectAssistant(workspace)


__all__ = [
    "ProjectMilestone",
    "ProjectCheckpoint",
    "Project",
    "ProjectAssistant",
    "create_project_assistant",
]

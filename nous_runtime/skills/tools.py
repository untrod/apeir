"""ToolCatalog adapter for progressive Skill discovery and loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from nous_runtime.skills.registry import SkillRegistry


class SkillToolRuntime:
    def __init__(self, workspace: str | Path, *, allow_mutations: bool = False) -> None:
        self.registry = SkillRegistry(workspace)
        self.allow_mutations = bool(allow_mutations)

    def specifications(self) -> tuple[dict[str, Any], ...]:
        specs = [
            _tool("skill_list", "List compact enabled Skill summaries.", {}),
            _tool(
                "skill_search",
                "Search Skill descriptions and requested capabilities.",
                {"query": {"type": "string"}},
            ),
            _tool(
                "skill_load",
                "Load one Skill's instructions and resource names without executing it.",
                {"skill_id": {"type": "string", "minLength": 1}},
                required=("skill_id",),
            ),
        ]
        if self.allow_mutations:
            specs.append(
                _tool(
                    "skill_install",
                    "Install a local Skill package without executing its scripts.",
                    {"source": {"type": "string", "minLength": 1}},
                    required=("source",),
                )
            )
        return tuple(specs)

    def execute(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        try:
            if name == "skill_list":
                return {"ok": True, "skills": self.registry.summaries()}
            if name == "skill_search":
                return {
                    "ok": True,
                    "skills": [
                        item.summary()
                        for item in self.registry.search(
                            str(arguments.get("query") or "")
                        )
                    ],
                }
            if name == "skill_load":
                return {
                    "ok": True,
                    "skill": self.registry.load(
                        str(arguments.get("skill_id") or "")
                    ).to_dict(),
                }
            if name == "skill_install":
                if not self.allow_mutations:
                    return {
                        "ok": False,
                        "error": "Skill installation requires an explicit user request.",
                    }
                return {
                    "ok": True,
                    "skill": self.registry.install(
                        str(arguments.get("source") or "")
                    ).to_dict(),
                }
            return {"ok": False, "error": f"unknown Skill tool: {name}"}
        except (KeyError, OSError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}


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


__all__ = ["SkillToolRuntime"]

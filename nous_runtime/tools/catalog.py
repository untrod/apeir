"""Unified, progressive discovery over existing governed tool runtimes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping

from nous_runtime.tools.models import ToolDefinition

if TYPE_CHECKING:
    from nous_runtime.extensions.models import ToolSpec


ToolExecutor = Callable[[str, Mapping[str, Any]], Any]
ExtensionExecutor = Callable[[str, str, Mapping[str, Any]], Any]
CATALOG_EXPAND_TOOL = "catalog_expand"


@dataclass(frozen=True)
class _CatalogEntry:
    definition: ToolDefinition
    executor: ToolExecutor | None


class ToolCatalog:
    """Discover tools uniformly while delegating all execution and policy."""

    def __init__(self) -> None:
        self._entries: dict[str, _CatalogEntry] = {}

    def register(
        self,
        definition: ToolDefinition,
        *,
        executor: ToolExecutor | None,
    ) -> None:
        if definition.tool_id == CATALOG_EXPAND_TOOL:
            raise ValueError(f"reserved tool id: {CATALOG_EXPAND_TOOL}")
        if definition.tool_id in self._entries:
            raise ValueError(f"duplicate tool id: {definition.tool_id}")
        if definition.availability == "available" and executor is None:
            raise ValueError(
                f"available tool requires an executor: {definition.tool_id}"
            )
        self._entries[definition.tool_id] = _CatalogEntry(definition, executor)

    def register_runtime(
        self,
        runtime: Any,
        *,
        provider_id: str = "workspace-runtime",
    ) -> None:
        specifications = getattr(runtime, "specifications", None)
        execute = getattr(runtime, "execute", None)
        if not callable(specifications) or not callable(execute):
            raise TypeError("runtime tools require specifications() and execute()")
        for raw in specifications() or ():
            if not isinstance(raw, Mapping):
                raise TypeError("runtime tool specification must be an object")
            definition = _runtime_definition(raw, provider_id=provider_id)
            self.register(definition, executor=execute)

    def register_extension_tools(
        self,
        extension_id: str,
        tools: Iterable["ToolSpec"],
        *,
        executor: ExtensionExecutor,
    ) -> None:
        extension_id = str(extension_id or "").strip()
        if not extension_id:
            raise ValueError("extension_id is required")
        for tool in tools:
            errors = tool.validate()
            if errors:
                raise ValueError("invalid extension tool: " + "; ".join(errors))
            extension_key = _safe_identifier(extension_id)[:20]
            tool_key = _safe_identifier(tool.name)[:32]
            tool_id = f"extension_{extension_key}_{tool_key}"

            def invoke(
                _tool_id: str,
                arguments: Mapping[str, Any],
                *,
                _name: str = tool.name,
            ) -> Any:
                return executor(extension_id, _name, arguments)

            definition = ToolDefinition(
                tool_id=tool_id,
                description=tool.description or f"Extension tool {tool.name}",
                input_schema=dict(tool.input_schema),
                output_schema=dict(tool.output_schema),
                capability_id="tool.invoke",
                category="mcp" if tool.protocol == "mcp" else "extension",
                effect_class=tool.effect,
                execution_backend=f"extension:{tool.protocol}",
                requires_network=tool.protocol in {"mcp", "openapi"},
                approval_policy="kernel_required",
                source=f"extension:{extension_id}",
                metadata={
                    "authority": "none",
                    "extension_id": extension_id,
                    "source_tool_name": tool.name,
                    "operation": tool.operation,
                },
            )
            self.register(definition, executor=invoke)

    def categories(self) -> tuple[dict[str, Any], ...]:
        grouped: dict[str, list[ToolDefinition]] = {}
        for entry in self._entries.values():
            grouped.setdefault(entry.definition.category, []).append(entry.definition)
        return tuple(
            {
                "category": category,
                "tool_count": len(items),
                "effects": sorted({item.effect_class for item in items}),
                "available": sum(item.availability == "available" for item in items),
                "expand_with": CATALOG_EXPAND_TOOL,
                "authority": "none",
            }
            for category, items in sorted(grouped.items())
        )

    def discover(
        self,
        *,
        category: str = "",
        query: str = "",
        include_schemas: bool = False,
    ) -> tuple[dict[str, Any], ...]:
        category = str(category or "").strip().casefold()
        query = str(query or "").strip().casefold()
        matches: list[ToolDefinition] = []
        for entry in self._entries.values():
            item = entry.definition
            if category and item.category.casefold() != category:
                continue
            if (
                query
                and query
                not in " ".join(
                    (item.tool_id, item.description, item.category, item.capability_id)
                ).casefold()
            ):
                continue
            matches.append(item)
        matches.sort(key=lambda item: (item.category, item.tool_id))
        return tuple(
            item.to_dict() if include_schemas else item.summary() for item in matches
        )

    def expand(self, category: str) -> dict[str, Any]:
        category = str(category or "").strip()
        if not category:
            return {"ok": False, "error": "tool category is required"}
        tools = self.discover(category=category, include_schemas=True)
        if not tools:
            return {"ok": False, "error": f"unknown tool category: {category}"}
        return {
            "ok": True,
            "category": category,
            "tools": list(tools),
            "authority": "none",
        }

    def require(self, tool_id: str) -> ToolDefinition:
        entry = self._entries.get(str(tool_id or ""))
        if entry is None:
            raise KeyError(tool_id)
        return entry.definition

    def specifications(self) -> tuple[dict[str, Any], ...]:
        """Return full schemas for invocation-boundary capability binding."""
        return (
            self._expand_definition().model_specification(),
            *(
                entry.definition.model_specification()
                for entry in self._entries.values()
            ),
        )

    def prompt_specifications(self) -> tuple[dict[str, Any], ...]:
        """Return only the discovery tool until the model expands a category."""
        return (self._expand_definition().model_specification(),)

    def execute(self, tool_id: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if tool_id == CATALOG_EXPAND_TOOL:
            return self.expand(str(arguments.get("category") or ""))
        entry = self._entries.get(str(tool_id or ""))
        if entry is None:
            return {"ok": False, "error": f"unknown catalog tool: {tool_id}"}
        if entry.definition.availability != "available" or entry.executor is None:
            return {
                "ok": False,
                "error": entry.definition.unavailable_reason or "tool is unavailable",
            }
        try:
            value = entry.executor(entry.definition.tool_id, dict(arguments))
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "error_code": type(exc).__name__,
            }
        if isinstance(value, Mapping):
            return dict(value)
        return {"ok": True, "result": value}

    @staticmethod
    def _expand_definition() -> ToolDefinition:
        return ToolDefinition(
            tool_id=CATALOG_EXPAND_TOOL,
            description="Load full schemas for one tool capability category.",
            input_schema={
                "type": "object",
                "properties": {
                    "category": {"type": "string", "minLength": 1},
                },
                "required": ["category"],
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
            capability_id="tool.catalog.read",
            category="task",
            effect_class="none",
            execution_backend="tool-catalog",
            approval_policy="none",
            metadata={"authority": "none"},
        )


def _runtime_definition(
    specification: Mapping[str, Any],
    *,
    provider_id: str,
) -> ToolDefinition:
    function = specification.get("function")
    raw = function if isinstance(function, Mapping) else specification
    tool_id = str(raw.get("name") or "").strip()
    description = str(raw.get("description") or "").strip()
    input_schema = raw.get("parameters") or raw.get("input_schema") or {}
    if not isinstance(input_schema, Mapping):
        raise TypeError(f"input schema must be an object: {tool_id}")
    metadata = _runtime_metadata(tool_id)
    return ToolDefinition(
        tool_id=tool_id,
        description=description or f"Runtime tool {tool_id}",
        input_schema=dict(input_schema),
        output_schema=dict(raw.get("output_schema") or {}),
        capability_id=metadata["capability_id"],
        category=metadata["category"],
        effect_class=metadata["effect_class"],
        execution_backend=provider_id,
        timeout_seconds=metadata["timeout_seconds"],
        requires_network=metadata["requires_network"],
        requires_filesystem=metadata["requires_filesystem"],
        approval_policy=metadata["approval_policy"],
        source=f"runtime:{provider_id}",
        metadata={"authority": "none"},
    )


def _runtime_metadata(tool_id: str) -> dict[str, Any]:
    explicit = {
        "list_workspace": ("files", "filesystem.read", "read"),
        "read_file": ("files", "filesystem.read", "read"),
        "search_workspace": ("files", "filesystem.read", "read"),
        "find_workspace": ("files", "filesystem.read", "read"),
        "write_file": ("files", "filesystem.write", "write"),
        "write_files": ("files", "filesystem.write", "write"),
        "run_command": ("shell", "process.execute", "execute"),
        "create_document": ("document", "document.create", "write"),
        "render_document": ("document", "document.render", "execute"),
        "fetch_public_url": ("web", "network.fetch", "network"),
        "create_simulation": ("scientific", "simulation.create", "write"),
        "run_simulation": ("scientific", "simulation.run", "execute"),
        "replay_simulation": ("scientific", "simulation.replay", "execute"),
        "cancel_simulation": ("scientific", "simulation.cancel", "write"),
        "analyze_scientific_run": (
            "scientific",
            "scientific.analyze",
            "execute",
        ),
        "create_environment": ("environment", "environment.create", "write"),
        "start_environment": ("environment", "environment.start", "execute"),
        "run_environment": ("environment", "environment.run", "execute"),
        "stop_environment": ("environment", "environment.stop", "write"),
        "destroy_environment": ("environment", "environment.destroy", "write"),
        "git_status": ("git", "git.read", "read"),
        "git_diff": ("git", "git.read", "read"),
        "git_log": ("git", "git.read", "read"),
        "git_branch": ("git", "git.read", "read"),
        "git_show": ("git", "git.read", "read"),
        "artifact_list": ("artifact", "artifact.read", "read"),
        "artifact_inspect": ("artifact", "artifact.read", "read"),
        "artifact_get": ("artifact", "artifact.read", "read"),
        "artifact_put": ("artifact", "artifact.store", "write"),
    }
    category, capability, effect = explicit.get(
        tool_id,
        ("other", "tool.invoke", "unknown"),
    )
    requires_filesystem = category in {
        "artifact",
        "files",
        "git",
        "shell",
        "document",
        "environment",
    }
    requires_network = effect == "network"
    approval = "none" if effect in {"none", "read"} else "runtime_policy"
    return {
        "category": category,
        "capability_id": capability,
        "effect_class": effect,
        "timeout_seconds": 120 if category in {"shell", "environment"} else 60,
        "requires_network": requires_network,
        "requires_filesystem": requires_filesystem,
        "approval_policy": approval,
    }


def _safe_identifier(value: str) -> str:
    result = "".join(character if character.isalnum() else "_" for character in value)
    result = result.strip("_")
    if not result:
        raise ValueError("tool identifier contains no usable characters")
    return result[:80]


__all__ = ["CATALOG_EXPAND_TOOL", "ToolCatalog"]

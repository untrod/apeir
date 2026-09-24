"""Workspace-scoped tools used by the model-backed Nous agent loop."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import tempfile
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Mapping

from nous_runtime.agents.adapters.workspace_guard import WorkspaceGuard
from nous_runtime.capability.sandbox import ExecutionSandbox, SandboxConfig
from nous_runtime.governance.effect_gate import EffectGate
from nous_runtime.execution.executables import resolve_executable

_MAX_READ_BYTES = 262_144
_MAX_WRITE_BYTES = 1_048_576
_MAX_BATCH_FILES = 24
_MAX_BATCH_WRITE_BYTES = 2_097_152
_MAX_LIST_ENTRIES = 400
_MAX_COMMAND_OUTPUT = 65_536
_SENSITIVE_ENV_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")

_RUNTIME_TOOL_CAPABILITIES = {
    "create_document": "document.create",
    "render_document": "document.render",
    "create_environment": "environment.create",
    "start_environment": "environment.start",
    "run_environment": "environment.run",
    "stop_environment": "environment.stop",
    "destroy_environment": "environment.destroy",
    "fetch_public_url": "network.fetch",
    "create_simulation": "simulation.create",
    "run_simulation": "simulation.run",
    "replay_simulation": "simulation.replay",
    "cancel_simulation": "simulation.cancel",
    "analyze_scientific_run": "scientific.analyze",
}


def mutation_is_explicit(text: str) -> bool:
    """Return whether the user explicitly requested a governed effect."""
    value = text.casefold()
    denied = (
        "do not modify",
        "don't modify",
        "read only",
        "只读",
        "不要修改",
        "不要写入",
        "仅查看",
    )
    if any(marker in value for marker in denied):
        return False
    requested = (
        "create ",
        "write ",
        "modify ",
        "edit ",
        "update ",
        "fix ",
        "implement ",
        "run tests",
        "render document",
        "create environment",
        "start environment",
        "run environment",
        "stop environment",
        "destroy environment",
        "fetch ",
        "search the web",
        "network search",
        "create simulation",
        "run simulation",
        "replay simulation",
        "cancel simulation",
        "analyze scientific",
        "创建",
        "写入",
        "修改",
        "编辑",
        "更新",
        "修复",
        "实现",
        "运行测试",
        "渲染文档",
        "创建环境",
        "启动环境",
        "运行环境",
        "停止环境",
        "销毁环境",
        "请联网",
        "联网获取",
        "联网搜索",
        "访问网址",
        "抓取网页",
        "网络搜索",
        "创建模拟",
        "运行模拟",
        "重放模拟",
        "取消模拟",
        "分析科学",
    )
    return any(marker in value for marker in requested)


def _runtime_tool_specifications() -> list[dict[str, Any]]:
    """Provider-neutral schemas for governed Runtime service tools."""
    object_value = {"type": "object", "additionalProperties": True}
    identifier = {"type": "string", "minLength": 1}
    specs = [
        _tool(
            "create_document",
            "Create a versioned Document IR; approval is required.",
            {"document": object_value},
            required=("document",),
        ),
        _tool(
            "render_document",
            "Render and verify a document as DOCX and/or PDF.",
            {
                "document_id": identifier,
                "formats": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["docx", "pdf"]},
                },
            },
            required=("document_id",),
        ),
        _tool(
            "create_environment",
            "Create a bounded execution-environment contract.",
            {"environment": object_value},
            required=("environment",),
        ),
        _tool(
            "run_environment",
            "Run an argv array inside a ready governed environment.",
            {
                "environment_id": identifier,
                "argv": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "cwd": {"type": "string"},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 3600},
                "max_output_bytes": {"type": "integer", "minimum": 1},
                "env": object_value,
            },
            required=("environment_id", "argv"),
        ),
        _tool(
            "fetch_public_url",
            "Fetch a public HTTP(S) URL through the governed Network Gateway.",
            {
                "url": {"type": "string", "minLength": 1},
                "method": {"type": "string", "enum": ["GET", "HEAD", "POST"]},
                "headers": object_value,
                "body_ref": {"type": "string"},
            },
            required=("url",),
        ),
        _tool(
            "create_simulation",
            "Create a reproducible Simulation contract.",
            {"simulation": object_value},
            required=("simulation",),
        ),
        _tool(
            "run_simulation",
            "Execute a bounded Simulation through EnvironmentRuntime.",
            {
                "simulation_id": identifier,
                "replay_of": {"type": "string"},
            },
            required=("simulation_id",),
        ),
        _tool(
            "replay_simulation",
            "Replay and tolerance-check a Simulation run.",
            {"run_id": identifier},
            required=("run_id",),
        ),
        _tool(
            "analyze_scientific_run",
            "Analyze a Simulation run and produce claims plus verified reports.",
            {"analysis": object_value},
            required=("analysis",),
        ),
    ]
    for name, description, field in (
        ("start_environment", "Start a governed environment.", "environment_id"),
        ("stop_environment", "Stop a governed environment.", "environment_id"),
        (
            "destroy_environment",
            "Destroy governed environment provider state.",
            "environment_id",
        ),
        (
            "cancel_simulation",
            "Request cancellation of an active Simulation.",
            "simulation_id",
        ),
    ):
        specs.append(_tool(name, description, {field: identifier}, required=(field,)))
    return specs


class WorkspaceToolRuntime:
    """Execute a bounded tool set inside one selected workspace."""

    def __init__(
        self,
        workspace: str,
        *,
        allow_mutations: bool = False,
        gate: EffectGate | None = None,
        authorization_context: Mapping[str, Any] | None = None,
        governance_surface: str = "server",
    ) -> None:
        self.guard = WorkspaceGuard(workspace)
        self.root = Path(self.guard.root)
        self.allow_mutations = bool(allow_mutations)
        self.gate = gate or EffectGate()
        self.authorization_context = dict(authorization_context or {})
        self.governance_surface = str(governance_surface or "server")
        self._effect_sequence = 0

    def specifications(self) -> tuple[dict[str, Any], ...]:
        specs = [
            _tool(
                "list_workspace",
                "List files and directories inside the active workspace.",
                {
                    "path": {
                        "type": "string",
                        "description": "Relative directory; default is .",
                    },
                    "max_depth": {"type": "integer", "minimum": 0, "maximum": 4},
                },
            ),
            _tool(
                "read_file",
                "Read a UTF-8 text file inside the active workspace.",
                {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer", "minimum": 1},
                    "end_line": {"type": "integer", "minimum": 1},
                },
                required=("path",),
            ),
            _tool(
                "search_workspace",
                "Search text in workspace files without leaving the workspace.",
                {
                    "query": {"type": "string"},
                    "path": {
                        "type": "string",
                        "description": "Relative directory; default is .",
                    },
                },
                required=("query",),
            ),
            _tool(
                "find_workspace",
                "Find workspace paths by a bounded glob-style pattern.",
                {
                    "pattern": {"type": "string", "minLength": 1},
                    "path": {
                        "type": "string",
                        "description": "Relative directory; default is .",
                    },
                },
                required=("pattern",),
            ),
        ]
        if self.allow_mutations:
            specs.extend(
                [
                    _tool(
                        "write_file",
                        "Create or replace a UTF-8 file inside the active workspace.",
                        {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        required=("path", "content"),
                    ),
                    _tool(
                        "write_files",
                        "Create or replace several UTF-8 project files inside the active workspace; each file write is atomic and audited.",
                        {
                            "files": {
                                "type": "array",
                                "maxItems": _MAX_BATCH_FILES,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "path": {"type": "string"},
                                        "content": {"type": "string"},
                                    },
                                    "required": ["path", "content"],
                                },
                            }
                        },
                        required=("files",),
                    ),
                    _tool(
                        "run_command",
                        "Run a bounded development command in the active workspace.",
                        {
                            "command": {
                                "oneOf": [
                                    {"type": "array", "items": {"type": "string"}},
                                    {"type": "string"},
                                ]
                            },
                            "timeout_seconds": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 120,
                            },
                        },
                        required=("command",),
                    ),
                ]
            )
            specs.extend(_runtime_tool_specifications())
        return tuple(specs)

    @property
    def mutation_tool_names(self) -> frozenset[str]:
        return frozenset(
            {"write_file", "write_files", "run_command", *_RUNTIME_TOOL_CAPABILITIES}
        )

    def execute(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        handlers = {
            "list_workspace": self._list_workspace,
            "read_file": self._read_file,
            "search_workspace": self._search_workspace,
            "find_workspace": self._find_workspace,
            "write_file": self._write_file,
            "write_files": self._write_files,
            "run_command": self._run_command,
        }
        if name in _RUNTIME_TOOL_CAPABILITIES:
            if not self.allow_mutations:
                return {
                    "ok": False,
                    "error": "Runtime effects require an explicit user request.",
                }
            return self._execute_runtime_capability(str(name), dict(arguments))
        handler = handlers.get(str(name))
        if handler is None:
            return {"ok": False, "error": f"Unknown Nous tool: {name}"}
        if (
            name in {"write_file", "write_files", "run_command"}
            and not self.allow_mutations
        ):
            return {
                "ok": False,
                "error": "Workspace mutation requires explicit user authorization.",
            }
        try:
            return dict(handler(dict(arguments)))
        except (OSError, UnicodeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    def _execute_runtime_capability(
        self, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        from nous_runtime.capability.resolver import execute_capability_observation

        capability_id = _RUNTIME_TOOL_CAPABILITIES[name]
        envelope = {
            "create_document": "document",
            "create_environment": "environment",
            "create_simulation": "simulation",
            "analyze_scientific_run": "analysis",
        }.get(name, "")
        if envelope and isinstance(arguments.get(envelope), Mapping):
            arguments = dict(arguments[envelope])
        observation = execute_capability_observation(
            capability_id,
            _authorization_context=self.authorization_context or None,
            _governance_surface=self.governance_surface,
            _workspace_root=str(self.root),
            **arguments,
        )
        metadata = dict(observation.metadata or {})
        if observation.status != "success":
            return {
                "ok": False,
                "capability_id": capability_id,
                "error": "; ".join(observation.errors) or "Runtime capability failed.",
                "error_code": str(
                    metadata.get("error_code") or "NOUS_EXECUTION_FAILED"
                ),
                "approval_required": bool(metadata.get("approval_required")),
                "approval_request_id": str(metadata.get("approval_request_id") or ""),
                "execution_scope": str(
                    metadata.get("execution_scope") or "runtime-service"
                ),
                "kernel_traversed": False,
            }
        data = dict(observation.data or {})
        return {
            "ok": True,
            "capability_id": capability_id,
            "result": data.get("result", data),
            "execution_scope": str(
                metadata.get("execution_scope") or "runtime-service"
            ),
            "kernel_traversed": False,
        }

    def _path(self, value: Any, *, allow_nonexistent: bool = False) -> Path:
        text = str(value or ".")
        return Path(self.guard.validate_path(text, allow_nonexistent=allow_nonexistent))

    def _list_workspace(self, arguments: dict[str, Any]) -> dict[str, Any]:
        root = self._path(arguments.get("path") or ".")
        if not root.is_dir():
            raise ValueError("The requested workspace path is not a directory.")
        max_depth = max(0, min(int(arguments.get("max_depth") or 2), 4))
        entries: list[dict[str, Any]] = []
        for item in sorted(
            root.rglob("*"), key=lambda value: value.as_posix().casefold()
        ):
            relative = item.relative_to(root)
            if len(relative.parts) > max_depth + 1:
                continue
            if any(
                part in {".git", ".nous", "node_modules", "target", "__pycache__"}
                for part in relative.parts
            ):
                continue
            entries.append(
                {
                    "path": item.relative_to(self.root).as_posix(),
                    "type": "directory" if item.is_dir() else "file",
                    "size_bytes": item.stat().st_size if item.is_file() else 0,
                }
            )
            if len(entries) >= _MAX_LIST_ENTRIES:
                break
        return {
            "ok": True,
            "workspace": str(self.root),
            "entries": entries,
            "truncated": len(entries) >= _MAX_LIST_ENTRIES,
        }

    def _read_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = self._path(arguments.get("path"))
        if not path.is_file():
            raise ValueError("The requested workspace path is not a file.")
        if path.stat().st_size > _MAX_READ_BYTES:
            raise ValueError("The file exceeds the 256 KiB agent read limit.")
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        start = max(1, int(arguments.get("start_line") or 1))
        end = min(
            len(lines), int(arguments.get("end_line") or min(start + 399, len(lines)))
        )
        selected = lines[start - 1 : end]
        return {
            "ok": True,
            "path": path.relative_to(self.root).as_posix(),
            "start_line": start,
            "end_line": end,
            "content": "\n".join(selected),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    def _search_workspace(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query") or "")
        if not query:
            raise ValueError("Search query is required.")
        root = self._path(arguments.get("path") or ".")
        matches: list[dict[str, Any]] = []
        candidates = [root] if root.is_file() else root.rglob("*")
        for path in candidates:
            if not path.is_file() or path.stat().st_size > _MAX_READ_BYTES:
                continue
            relative = path.relative_to(self.root)
            if any(
                part in {".git", ".nous", "node_modules", "target", "__pycache__"}
                for part in relative.parts
            ):
                continue
            try:
                for line_number, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), 1
                ):
                    if query.casefold() in line.casefold():
                        matches.append(
                            {
                                "path": relative.as_posix(),
                                "line": line_number,
                                "text": line[:500],
                            }
                        )
                        if len(matches) >= 100:
                            return {"ok": True, "matches": matches, "truncated": True}
            except UnicodeError:
                continue
        return {"ok": True, "matches": matches, "truncated": False}

    def _find_workspace(self, arguments: dict[str, Any]) -> dict[str, Any]:
        pattern = str(arguments.get("pattern") or "").strip()
        if not pattern or len(pattern) > 200 or "\x00" in pattern:
            raise ValueError("A bounded path pattern is required.")
        root = self._path(arguments.get("path") or ".")
        if not root.is_dir():
            raise ValueError("The requested workspace path is not a directory.")
        matches: list[dict[str, Any]] = []
        for item in sorted(
            root.rglob("*"), key=lambda value: value.as_posix().casefold()
        ):
            relative_to_root = item.relative_to(root).as_posix()
            relative_to_workspace = item.relative_to(self.root)
            if any(
                part in {".git", ".nous", "node_modules", "target", "__pycache__"}
                for part in relative_to_workspace.parts
            ):
                continue
            if not fnmatch(relative_to_root, pattern) and not fnmatch(
                item.name, pattern
            ):
                continue
            matches.append(
                {
                    "path": relative_to_workspace.as_posix(),
                    "type": "directory" if item.is_dir() else "file",
                }
            )
            if len(matches) >= 200:
                return {"ok": True, "matches": matches, "truncated": True}
        return {"ok": True, "matches": matches, "truncated": False}

    def _write_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = self._path(arguments.get("path"), allow_nonexistent=True)
        relative = path.relative_to(self.root)
        if relative.parts and relative.parts[0] in {".git", ".nous"}:
            raise ValueError("Nous internal and Git metadata are protected.")
        if relative.as_posix() == "workspace.json":
            raise ValueError("workspace.json is managed by Nous.")
        content = str(arguments.get("content") or "")
        encoded = content.encode("utf-8")
        if len(encoded) > _MAX_WRITE_BYTES:
            raise ValueError("The write exceeds the 1 MiB agent limit.")
        before = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
        action, _decision = self.gate.propose_action(
            "file_write",
            relative.as_posix(),
            {"size_bytes": len(encoded), "before_sha256": before},
        )
        approval = self.gate.request_approval(
            action, approver="explicit_workspace_request"
        )

        def effect(_params: dict[str, Any]) -> dict[str, Any]:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(
                prefix=".nous-write-", dir=path.parent
            )
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return {"path": relative.as_posix(), "size_bytes": len(encoded)}

        receipt = self.gate.execute(action, approval, effect)
        artifact_id = ""
        if receipt.success:
            from nous_runtime.artifact import ArtifactManager, ArtifactType, registry

            artifact_type = (
                ArtifactType.CODE
                if path.suffix.casefold()
                in {".py", ".js", ".ts", ".tsx", ".rs", ".c", ".h", ".cpp"}
                else ArtifactType.REPORT
                if path.suffix.casefold() in {".md", ".rst"}
                else ArtifactType.FILE
            )
            artifact = ArtifactManager(registry).create(
                artifact_type,
                path.name,
                location=relative.as_posix(),
                creator="nous.workspace-agent",
                metadata={"receipt_id": receipt.receipt_id},
            )
            artifact_id = artifact.id
        return {
            "ok": receipt.success,
            "path": relative.as_posix(),
            "size_bytes": len(encoded),
            "before_sha256": before,
            "after_sha256": hashlib.sha256(path.read_bytes()).hexdigest()
            if receipt.success
            else "",
            "receipt_id": receipt.receipt_id,
            "artifact_id": artifact_id,
        }

    def _write_files(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw_files = arguments.get("files")
        if not isinstance(raw_files, list) or not raw_files:
            raise ValueError("files must be a non-empty array.")
        if len(raw_files) > _MAX_BATCH_FILES:
            raise ValueError(f"A batch may contain at most {_MAX_BATCH_FILES} files.")
        prepared: list[tuple[str, str]] = []
        total = 0
        seen: set[str] = set()
        for item in raw_files:
            if not isinstance(item, Mapping):
                raise ValueError("Each batch item must contain path and content.")
            path = self._path(item.get("path"), allow_nonexistent=True)
            relative = path.relative_to(self.root).as_posix()
            if relative in {"", ".", "./"} or relative in seen:
                raise ValueError("Batch file paths must be non-empty and unique.")
            if relative == "workspace.json" or relative.split("/", 1)[0] in {
                ".git",
                ".nous",
            }:
                raise ValueError(
                    "Nous internal, workspace, and Git metadata are protected."
                )
            content = str(item.get("content") or "")
            size = len(content.encode("utf-8"))
            if size > _MAX_WRITE_BYTES:
                raise ValueError(f"{relative} exceeds the 1 MiB file limit.")
            total += size
            seen.add(relative)
            prepared.append((relative, content))
        if total > _MAX_BATCH_WRITE_BYTES:
            raise ValueError("The batch exceeds the 2 MiB project write limit.")

        results = []
        for relative, content in prepared:
            result = self._write_file({"path": relative, "content": content})
            results.append(result)
            if not result.get("ok"):
                return {
                    "ok": False,
                    "files": results,
                    "file_count": len(results),
                    "error": f"Failed while writing {relative}.",
                }
        return {
            "ok": True,
            "files": results,
            "file_count": len(results),
            "total_size_bytes": total,
        }

    def _run_command(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw = arguments.get("command")
        command = (
            [str(item) for item in raw]
            if isinstance(raw, list)
            else shlex.split(str(raw or ""), posix=os.name != "nt")
        )
        self._validate_command(command)
        self._validate_command_paths(command[1:])
        resolved_executable = resolve_executable(command[0])
        if not resolved_executable:
            raise ValueError(f"Command executable was not found: {command[0]}")
        command[0] = resolved_executable
        timeout = max(1, min(int(arguments.get("timeout_seconds") or 60), 120))
        action, _decision = self.gate.propose_action(
            "shell_exec",
            command[0],
            {
                "arguments": command[1:],
                "timeout_seconds": timeout,
                "attempt": self._next_effect_attempt(),
            },
        )
        approval = self.gate.request_approval(
            action, approver="explicit_workspace_request"
        )

        def effect(_params: dict[str, Any]) -> dict[str, Any]:
            sandbox = ExecutionSandbox(
                SandboxConfig(
                    workspace_root=str(self.root),
                    allowed_commands=[Path(command[0]).name],
                    max_runtime_seconds=timeout,
                    max_output_bytes=_MAX_COMMAND_OUTPUT,
                    allow_network=False,
                    isolation_level="strict",
                )
            )
            completed = sandbox.run(
                shlex.join(command),
                cwd=str(self.root),
                env=_safe_environment(),
            )
            return {
                "exit_code": completed.returncode,
                "stdout": completed.stdout[-_MAX_COMMAND_OUTPUT:],
                "stderr": completed.stderr[-_MAX_COMMAND_OUTPUT:],
            }

        receipt = self.gate.execute(action, approval, effect)
        result = dict(receipt.result or {})
        return {
            "ok": receipt.success and result.get("exit_code") == 0,
            **result,
            "receipt_id": receipt.receipt_id,
        }

    def _next_effect_attempt(self) -> int:
        """Return a per-runtime nonce for an independently approved effect.

        Replay protection still rejects reuse of the same CanonicalAction, but
        an agent may intentionally rerun a test after repairing the workspace.
        """
        self._effect_sequence += 1
        return self._effect_sequence

    @staticmethod
    def _validate_command(command: list[str]) -> None:
        if not command:
            raise ValueError("Command is required.")
        executable = Path(command[0]).name.casefold().removesuffix(".exe")
        arguments = [item.casefold() for item in command[1:]]
        allowed = False
        if (
            executable == "git"
            and arguments
            and arguments[0] in {"status", "diff", "log", "show"}
        ):
            allowed = True
        elif executable in {"pytest", "ruff"}:
            allowed = True
        elif (
            executable == "python"
            and len(arguments) >= 2
            and arguments[:2] in (["-m", "pytest"], ["-m", "compileall"])
        ):
            allowed = True
        elif (
            executable == "npm"
            and arguments
            and (
                arguments[0] == "test"
                or (
                    len(arguments) >= 2
                    and arguments[:2]
                    in (
                        ["run", "test"],
                        ["run", "lint"],
                        ["run", "typecheck"],
                        ["run", "build"],
                    )
                )
            )
        ):
            allowed = True
        elif (
            executable == "cargo"
            and arguments
            and arguments[0] in {"test", "check", "clippy", "fmt"}
        ):
            allowed = True
        if not allowed:
            raise ValueError(
                "Command is outside the governed development-command allowlist."
            )
        if any(
            any(marker in item for marker in ("&&", "||", ";", "|", ">", "<"))
            for item in command
        ):
            raise ValueError("Shell operators are not allowed.")

    def _validate_command_paths(self, arguments: list[str]) -> None:
        for argument in arguments:
            candidate = argument.split("=", 1)[-1] if "=" in argument else argument
            if ".." in Path(candidate).parts or Path(candidate).is_absolute():
                raise ValueError(
                    "Command paths must remain relative to the active workspace."
                )
        self.guard.validate_command_args(tuple(arguments))


def parse_tool_call(call: Mapping[str, Any]) -> tuple[str, str, dict[str, Any]]:
    function = (
        call.get("function") if isinstance(call.get("function"), Mapping) else call
    )
    name = str(function.get("name") or call.get("name") or "")
    call_id = str(call.get("id") or f"call-{name}")
    raw_arguments = function.get("arguments", call.get("arguments", {}))
    if isinstance(raw_arguments, str):
        arguments = json.loads(raw_arguments or "{}")
    elif isinstance(raw_arguments, Mapping):
        arguments = dict(raw_arguments)
    else:
        raise ValueError("Tool arguments must be a JSON object.")
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be a JSON object.")
    return call_id, name, arguments


def tool_protocol_prompt(specifications: tuple[Mapping[str, Any], ...]) -> str:
    names = [
        str((item.get("function") or {}).get("name") or "")
        for item in specifications
        if isinstance(item.get("function"), Mapping)
    ]
    available = ", ".join(name for name in names if name)
    contracts = []
    for item in specifications:
        function = (
            item.get("function") if isinstance(item.get("function"), Mapping) else {}
        )
        parameters = (
            function.get("parameters")
            if isinstance(function.get("parameters"), Mapping)
            else {}
        )
        properties = (
            parameters.get("properties")
            if isinstance(parameters.get("properties"), Mapping)
            else {}
        )
        contracts.append(
            {
                "name": str(function.get("name") or ""),
                "required": list(parameters.get("required") or ()),
                "arguments": {
                    str(name): str(schema.get("type") or "value")
                    for name, schema in properties.items()
                    if isinstance(schema, Mapping)
                },
            }
        )
    return (
        "Workspace tools available to Nous: "
        f"{available}. Contracts: "
        + json.dumps(contracts, ensure_ascii=False, separators=(",", ":"))
        + ". When the request depends on current workspace state, "
        "you must use a tool before answering. Prefer the provider's native "
        "tool-call mechanism when it is available. If native tool calling is "
        "unavailable, respond with exactly NOUS_TOOL_CALL followed by one "
        "compact JSON object with the shape "
        '{"name":"tool_name","arguments":{...}} and no other text. '
        "For a project with several substantial files, use one write_file call "
        "per file so each tool request remains complete and verifiable. "
        "After Nous returns a tool result, continue the task and use another "
        "tool when necessary."
    )


def parse_text_tool_call(
    content: Any,
    allowed_names: set[str],
) -> dict[str, Any] | None:
    if not isinstance(content, str):
        return None
    text = content.strip()
    marker = "NOUS_TOOL_CALL"
    if marker in text:
        text = text.split(marker, 1)[1].strip()
    elif not text.startswith("{"):
        return None
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        payload, _offset = json.JSONDecoder().raw_decode(text.strip())
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    name = str(payload.get("name") or "")
    arguments = payload.get("arguments") or {}
    if name not in allowed_names or not isinstance(arguments, Mapping):
        return None
    return {
        "id": f"protocol-{name}",
        "name": name,
        "arguments": dict(arguments),
    }


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


def _safe_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not any(marker in key.upper() for marker in _SENSITIVE_ENV_MARKERS)
    }

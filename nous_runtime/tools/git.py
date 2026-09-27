"""Read-only Git tools executed through the existing process sandbox."""

from __future__ import annotations

import os
import hashlib
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping

from nous_runtime.agents.adapters.workspace_guard import WorkspaceGuard
from nous_runtime.execution.executables import resolve_executable
from nous_runtime.kernel.sandbox import ProcessSandbox, SandboxPolicy


_MAX_OUTPUT = 128 * 1024
_MAX_SNAPSHOT_BYTES = 512 * 1024 * 1024
_MAX_SNAPSHOT_FILES = 100_000
_HOST_STATE_NAMES = frozenset({".nous", ".apeir", ".git"})
_GIT_RUNTIME_DEPENDENCIES = (
    "libintl-8.dll",
    "libpcre2-8-0.dll",
    "libiconv-2.dll",
    "zlib1.dll",
)
_REVISION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@{}~^:+-]{0,199}$")


class GitToolRuntime:
    """Expose fixed read-only Git operations for one workspace."""

    def __init__(self, workspace: str | Path) -> None:
        self.guard = WorkspaceGuard(str(workspace))
        self.root = Path(self.guard.root)
        self.git = resolve_executable("git")
        self.sandbox_available = self._has_strong_sandbox()

    def specifications(self) -> tuple[dict[str, Any], ...]:
        if (
            not self.git
            or not self.sandbox_available
            or not (self.root / ".git").exists()
        ):
            return ()
        path = {"type": "string", "description": "Optional workspace-relative path"}
        return (
            _tool("git_status", "Show the read-only Git working tree status.", {}),
            _tool(
                "git_diff",
                "Show a read-only Git diff, optionally staged or path-scoped.",
                {"staged": {"type": "boolean"}, "path": path},
            ),
            _tool(
                "git_log",
                "Show recent Git commits without changing repository state.",
                {"max_count": {"type": "integer", "minimum": 1, "maximum": 50}},
            ),
            _tool("git_branch", "List local Git branches.", {}),
            _tool(
                "git_show",
                "Show one Git revision without changing repository state.",
                {"revision": {"type": "string"}, "path": path},
            ),
        )

    def execute(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if not self.git:
            return {"ok": False, "error": "git executable is unavailable"}
        if not self.sandbox_available:
            return {"ok": False, "error": "strong process sandbox is unavailable"}
        if not (self.root / ".git").exists():
            return {"ok": False, "error": "workspace is not a Git repository"}
        handlers = {
            "git_status": self._status,
            "git_diff": self._diff,
            "git_log": self._log,
            "git_branch": self._branch,
            "git_show": self._show,
        }
        handler = handlers.get(str(name or ""))
        if handler is None:
            return {"ok": False, "error": f"unknown Git tool: {name}"}
        try:
            return handler(dict(arguments))
        except (OSError, RuntimeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    def _status(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        return self._run(("status", "--short", "--branch"))

    def _diff(self, arguments: dict[str, Any]) -> dict[str, Any]:
        command = ["diff", "--no-ext-diff", "--no-textconv"]
        if bool(arguments.get("staged")):
            command.append("--cached")
        path = self._relative_path(arguments.get("path"))
        if path:
            command.extend(("--", path))
        return self._run(tuple(command))

    def _log(self, arguments: dict[str, Any]) -> dict[str, Any]:
        count = max(1, min(int(arguments.get("max_count") or 10), 50))
        return self._run(
            (
                "log",
                f"-{count}",
                "--date=iso-strict",
                "--pretty=format:%H%x09%ad%x09%an%x09%s",
            )
        )

    def _branch(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        return self._run(("branch", "--list", "--format=%(refname:short)"))

    def _show(self, arguments: dict[str, Any]) -> dict[str, Any]:
        revision = str(arguments.get("revision") or "HEAD")
        if not _REVISION.fullmatch(revision) or revision.startswith("-"):
            raise ValueError("invalid Git revision")
        command = ["show", "--no-ext-diff", "--stat", "--oneline", revision]
        path = self._relative_path(arguments.get("path"))
        if path:
            command.extend(("--", path))
        return self._run(tuple(command))

    def _relative_path(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        path = Path(self.guard.validate_path(text, allow_nonexistent=False))
        return path.relative_to(self.root).as_posix()

    def _run(self, arguments: tuple[str, ...]) -> dict[str, Any]:
        assert self.git is not None
        metadata = self.root / ".git"
        if not metadata.is_dir():
            return {
                "ok": False,
                "error": "Git metadata pointers are not supported by the sandboxed Git runtime",
            }
        with tempfile.TemporaryDirectory(prefix="apeir-git-snapshot-") as temporary:
            snapshot_root = Path(temporary)
            worktree_snapshot = snapshot_root / "worktree"
            metadata_snapshot = snapshot_root / "metadata"
            runtime_snapshot = snapshot_root / "runtime"
            _copy_verified_tree(
                self.root,
                worktree_snapshot,
                ignored_names=_HOST_STATE_NAMES,
            )
            _copy_verified_tree(metadata, metadata_snapshot)
            git_executable = _copy_git_runtime(Path(self.git), runtime_snapshot)
            policy = SandboxPolicy(
                executable=str(git_executable),
                args=[
                    "--no-pager",
                    "--no-optional-locks",
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    "core.hooksPath=NUL",
                    "--git-dir",
                    str(metadata_snapshot),
                    "--work-tree",
                    str(worktree_snapshot),
                    *arguments,
                ],
                working_dir=str(worktree_snapshot),
                env=_safe_environment(),
                max_memory_bytes=256 * 1024 * 1024,
                max_cpu_time_seconds=30,
                max_output_bytes=_MAX_OUTPUT,
                max_staging_bytes=_MAX_SNAPSHOT_BYTES,
                max_staging_files=_MAX_SNAPSHOT_FILES,
                timeout_seconds=30,
                read_allowed_paths=[
                    str(worktree_snapshot),
                    str(metadata_snapshot),
                ],
                write_allowed_paths=[],
                network_allowed=False,
                isolation_level="strict",
                require_strong_isolation=True,
            )
            completed = ProcessSandbox(policy).run()
        return {
            "ok": completed.success,
            "exit_code": completed.exit_code,
            "stdout": completed.stdout[-_MAX_OUTPUT:],
            "stderr": completed.stderr[-_MAX_OUTPUT:],
            "security_grade": completed.security_grade,
        }

    def _has_strong_sandbox(self) -> bool:
        if not self.git:
            return False
        policy = SandboxPolicy(
            executable=self.git,
            args=["status", "--short"],
            working_dir=str(self.root),
            max_memory_bytes=256 * 1024 * 1024,
            max_cpu_time_seconds=30,
            max_output_bytes=_MAX_OUTPUT,
            timeout_seconds=30,
            read_allowed_paths=[str(self.root)],
            write_allowed_paths=[str(self.root)],
            network_allowed=False,
            isolation_level="strict",
            require_strong_isolation=True,
        )
        return bool(ProcessSandbox(policy).security_report()["strong"])


def _tool(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "additionalProperties": False,
            },
        },
    }


def _safe_environment() -> dict[str, str]:
    allowed = {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def _copy_verified_tree(
    source: Path,
    destination: Path,
    *,
    ignored_names: frozenset[str] = frozenset(),
) -> None:
    """Materialize an immutable, bounded tree without following host links."""

    before = _tree_digest(source, ignored_names=ignored_names)
    destination.parent.mkdir(parents=True, exist_ok=True)

    def ignore(_directory: str, names: list[str]) -> list[str]:
        return [name for name in names if name.casefold() in ignored_names]

    shutil.copytree(
        source,
        destination,
        copy_function=shutil.copy2,
        ignore=ignore if ignored_names else None,
    )
    after = _tree_digest(source, ignored_names=ignored_names)
    copied = _tree_digest(destination)
    if before != after or before != copied:
        raise ValueError("Git snapshot source changed while it was copied")


def _copy_trusted_executable(source: Path, destination: Path) -> None:
    """Materialize a trusted installed executable without its hard-link alias."""

    info = source.lstat()
    if getattr(info, "st_file_attributes", 0) & 0x400 or source.is_symlink():
        raise ValueError("reparse-point Git executables are unsupported")
    before = hashlib.sha256(source.read_bytes()).digest()
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    after = hashlib.sha256(source.read_bytes()).digest()
    copied = hashlib.sha256(destination.read_bytes()).digest()
    if before != after or before != copied:
        raise ValueError("Git executable changed while it was copied")


def _copy_git_runtime(resolved_git: Path, destination: Path) -> Path:
    """Copy the minimal Git for Windows builtin runtime into an isolated tree."""

    install_root = resolved_git.parent.parent
    core = install_root / "mingw64" / "bin"
    source_executable = core / "git.exe"
    if not source_executable.is_file():
        source_executable = resolved_git
        core = resolved_git.parent
    target_executable = destination / "git.exe"
    _copy_trusted_executable(source_executable, target_executable)
    for name in _GIT_RUNTIME_DEPENDENCIES:
        dependency = core / name
        if not dependency.is_file():
            raise ValueError(f"Git runtime dependency is unavailable: {name}")
        _copy_trusted_executable(dependency, destination / name)
    return target_executable


def _tree_digest(
    root: Path,
    *,
    ignored_names: frozenset[str] = frozenset(),
) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    files = 0
    size = 0
    paths: list[Path] = []
    for current, directories, filenames in os.walk(root, followlinks=False):
        directories[:] = [
            name for name in directories if name.casefold() not in ignored_names
        ]
        paths.extend(Path(current) / name for name in directories + filenames)
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        info = path.lstat()
        if getattr(info, "st_file_attributes", 0) & 0x400 or path.is_symlink():
            raise ValueError("reparse points are unsupported in Git snapshots")
        if path.is_dir():
            digest.update(b"d" + relative)
            continue
        if not path.is_file() or info.st_nlink > 1:
            raise ValueError("hard links are unsupported in Git snapshots")
        files += 1
        size += info.st_size
        if files > _MAX_SNAPSHOT_FILES or size > _MAX_SNAPSHOT_BYTES:
            raise ValueError("Git snapshot exceeds staging limits")
        digest.update(b"f" + relative + info.st_size.to_bytes(8, "big"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest(), files, size


__all__ = ["GitToolRuntime"]

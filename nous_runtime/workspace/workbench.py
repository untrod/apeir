"""Governed developer workbench backed by the canonical EventStream."""

from __future__ import annotations

import difflib
import hashlib
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from uuid import uuid4

from nous_runtime.capability.sandbox import run_process_strict
from nous_runtime.events import EventStream, RunEvent, RunState
from nous_runtime.workspace.isolation import normalize_workspace_path

_MAX_READ_BYTES = 512 * 1024
_MAX_WRITE_BYTES = 1024 * 1024
_MAX_FILES = 500
_MAX_SCAN_FILES = 5_000
_MAX_MATCHES = 200
_MAX_OUTPUT_BYTES = 256 * 1024
_IGNORED = {".git", ".nous", ".venv", "venv", "node_modules", "target", "dist", "build", "__pycache__", "artifacts"}
_CODE_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".rs", ".go", ".java", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".json", ".toml", ".yaml", ".yml", ".md", ".txt"}
_PROFILE_NAMES = ("python", "python-compile", "pytest", "node", "cargo-test")


def _python_executable() -> str:
    """Return a real interpreter, never the PyInstaller sidecar executable."""
    if getattr(sys, "frozen", False):
        return shutil.which("python") or shutil.which("python3") or ""
    return sys.executable


class WorkbenchError(ValueError):
    """A safe, user-actionable workbench request error."""


class WorkbenchConflict(WorkbenchError):
    """The file changed after the caller read or previewed it."""


class DeveloperWorkbench:
    """Bounded workspace file operations and fixed-profile execution.

    This service is intentionally not an arbitrary shell. All paths are scoped
    to one selected workspace, writes use compare-and-swap plus atomic replace,
    and runs accept a fixed profile instead of caller-supplied executables.
    Mutating actions append to the existing canonical EventStream.
    """

    def __init__(self, workspace_root: str | Path):
        self.root = Path(workspace_root).expanduser().resolve()
        if not self.root.is_dir():
            raise WorkbenchError("The active workspace does not exist or is not a directory.")
        self.events = EventStream(str(self.root))

    @staticmethod
    def profiles() -> list[dict[str, Any]]:
        candidates = {
            "python": _python_executable(),
            "python-compile": _python_executable(),
            "pytest": _python_executable(),
            "node": shutil.which("node") or "",
            "cargo-test": shutil.which("cargo") or "",
        }
        return [
            {"name": name, "available": bool(candidates[name]), "executable": candidates[name]}
            for name in _PROFILE_NAMES
        ]

    def list_files(self, *, path: str = ".", limit: int = _MAX_FILES) -> dict[str, Any]:
        base = self._resolve(path, require_exists=True)
        if not base.is_dir():
            raise WorkbenchError("The requested path is not a directory.")
        maximum = max(1, min(int(limit), _MAX_FILES))
        files: list[dict[str, Any]] = []
        for candidate in self._iter_files(base):
            relative = candidate.relative_to(self.root).as_posix()
            files.append({
                "path": relative,
                "size_bytes": candidate.stat().st_size,
                "modified_at": datetime.fromtimestamp(candidate.stat().st_mtime, timezone.utc).isoformat(),
                "language": self._language(candidate.suffix),
            })
            if len(files) >= maximum:
                break
        return {
            "workspace": str(self.root),
            "path": self._relative(base),
            "files": files,
            "total": len(files),
            "truncated": len(files) >= maximum,
            "profiles": self.profiles(),
        }

    def read_file(self, path: str) -> dict[str, Any]:
        target = self._resolve(path, require_exists=True)
        if not target.is_file():
            raise WorkbenchError("The requested path is not a file.")
        data = self._read_bytes(target)
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkbenchError("The workbench currently supports UTF-8 text files only.") from exc
        return {
            "path": self._relative(target),
            "content": content,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "language": self._language(target.suffix),
        }

    def search(self, query: str, *, path: str = ".", limit: int = _MAX_MATCHES) -> dict[str, Any]:
        needle = str(query or "").strip()
        if len(needle) < 2:
            raise WorkbenchError("Search query must contain at least two characters.")
        base = self._resolve(path, require_exists=True)
        maximum = max(1, min(int(limit), _MAX_MATCHES))
        matches: list[dict[str, Any]] = []
        candidates: Iterable[Path] = [base] if base.is_file() else self._iter_files(base)
        for candidate in candidates:
            try:
                data = self._read_bytes(candidate)
                lines = data.decode("utf-8").splitlines()
            except (WorkbenchError, UnicodeDecodeError, OSError):
                continue
            for line_number, line in enumerate(lines, 1):
                if needle.casefold() in line.casefold():
                    matches.append({"path": self._relative(candidate), "line": line_number, "text": line[:500]})
                    if len(matches) >= maximum:
                        return {"query": needle, "matches": matches, "total": len(matches), "truncated": True}
        return {"query": needle, "matches": matches, "total": len(matches), "truncated": False}

    def preview_write(self, path: str, content: str, *, expected_sha256: str = "") -> dict[str, Any]:
        target = self._write_target(path)
        encoded = str(content).encode("utf-8")
        if len(encoded) > _MAX_WRITE_BYTES:
            raise WorkbenchError("The write exceeds the 1 MiB workbench limit.")
        before = self._read_bytes(target) if target.is_file() else b""
        before_hash = hashlib.sha256(before).hexdigest() if target.is_file() else ""
        if target.is_file() and not expected_sha256:
            raise WorkbenchConflict("An expected SHA-256 is required when replacing an existing file.")
        if expected_sha256 and expected_sha256 != before_hash:
            raise WorkbenchConflict("The file changed after it was loaded; reload it before saving.")
        try:
            before_text = before.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkbenchError("The workbench currently supports UTF-8 text files only.") from exc
        relative = self._relative(target)
        diff = "\n".join(difflib.unified_diff(
            before_text.splitlines(),
            str(content).splitlines(),
            fromfile=f"a/{relative}",
            tofile=f"b/{relative}",
            lineterm="",
        ))
        return {
            "path": relative,
            "exists": target.is_file(),
            "changed": before != encoded,
            "before_sha256": before_hash,
            "after_sha256": hashlib.sha256(encoded).hexdigest(),
            "size_bytes": len(encoded),
            "diff": diff,
        }

    def write_file(self, path: str, content: str, *, expected_sha256: str = "") -> dict[str, Any]:
        preview = self.preview_write(path, content, expected_sha256=expected_sha256)
        target = self._write_target(path)
        run_id = self._new_run_id("write")
        task_id = f"workspace.write:{preview['path']}"
        self._start_run(run_id, task_id, "workspace.write", {"path": preview["path"]})
        if not preview["changed"]:
            self.events.emit_state_change(run_id, RunState.COMPLETED, task_id=task_id, changed=False)
            return {**preview, "ok": True, "run_id": run_id, "backup_path": ""}

        encoded = str(content).encode("utf-8")
        backup_path = ""
        try:
            # Recheck immediately before mutation to close the preview/write race.
            current = self._read_bytes(target) if target.is_file() else b""
            current_hash = hashlib.sha256(current).hexdigest() if target.is_file() else ""
            if current_hash != preview["before_sha256"]:
                raise WorkbenchConflict("The file changed while the save was being prepared; reload it.")
            if target.is_file():
                backup = self.root / ".nous" / "backups" / "workbench" / run_id / Path(*PurePosixPath(preview["path"]).parts)
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(current)
                backup_path = backup.relative_to(self.root).as_posix()
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=".nous-workbench-", dir=target.parent)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                # Validate the resolved parent again before the atomic replace.
                self._write_target(path)
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            self.events.emit(RunEvent(
                run_id=run_id,
                task_id=task_id,
                event_type="file.changed",
                actor="developer.workbench",
                payload={
                    "path": preview["path"],
                    "before_sha256": preview["before_sha256"],
                    "after_sha256": preview["after_sha256"],
                    "size_bytes": preview["size_bytes"],
                    "backup_path": backup_path,
                },
            ))
            self.events.emit_state_change(run_id, RunState.COMPLETED, task_id=task_id, changed=True)
            return {**preview, "ok": True, "run_id": run_id, "backup_path": backup_path}
        except Exception as exc:
            self.events.emit_state_change(run_id, RunState.FAILED, task_id=task_id, error=str(exc))
            raise

    def run_profile(self, profile: str, *, target: str = "", timeout_seconds: int = 60) -> dict[str, Any]:
        name = str(profile or "").strip().lower()
        timeout = max(1, min(int(timeout_seconds), 300))
        argv, target_path, is_test = self._profile_command(name, target)
        run_id = self._new_run_id("exec")
        task_id = f"workspace.run:{name}"
        self._start_run(run_id, task_id, "workspace.run", {"profile": name, "target": target_path})
        self.events.emit(RunEvent(
            run_id=run_id,
            task_id=task_id,
            event_type="command.started",
            actor="developer.workbench",
            payload={"profile": name, "argv": self._display_argv(argv), "cwd": "."},
        ))
        if is_test:
            self.events.emit(RunEvent(run_id=run_id, task_id=task_id, event_type="test.started", actor="developer.workbench", payload={"profile": name, "target": target_path}))
        try:
            result = run_process_strict(
                argv,
                cwd=str(self.root),
                timeout_seconds=timeout,
                max_output_bytes=_MAX_OUTPUT_BYTES,
            )
            for stream_name, text in (("stdout", result.stdout), ("stderr", result.stderr)):
                if text:
                    self.events.emit_chunked(RunEvent(
                        run_id=run_id,
                        task_id=task_id,
                        event_type="command.output",
                        actor="developer.workbench",
                        payload={"stream": stream_name, "text": text},
                    ))
            result_payload = {
                "profile": name,
                "target": target_path,
                "exit_code": result.returncode,
                "ok": result.ok,
                "runtime_seconds": result.runtime_seconds,
                "limit_exceeded": result.limit_exceeded,
                "sandbox_id": result.sandbox_id,
                "availability_state": result.availability_state,
                "security_grade": result.security_grade,
                "enforced_controls": list(result.enforced_controls),
                "unenforced_controls": list(result.unenforced_controls),
            }
            if is_test:
                self.events.emit(RunEvent(run_id=run_id, task_id=task_id, event_type="test.completed", actor="developer.workbench", payload=result_payload))
            final_state = RunState.COMPLETED if result.ok else RunState.FAILED
            self.events.emit_state_change(run_id, final_state, task_id=task_id, **result_payload)
            return {
                **result_payload,
                "run_id": run_id,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except Exception as exc:
            self.events.emit_state_change(run_id, RunState.FAILED, task_id=task_id, error=str(exc))
            raise

    def _profile_command(self, profile: str, target: str) -> tuple[list[str], str, bool]:
        if profile not in _PROFILE_NAMES:
            raise WorkbenchError(f"Unknown execution profile: {profile}. Allowed: {', '.join(_PROFILE_NAMES)}")
        if profile in {"python", "python-compile", "node", "pytest"}:
            default = "tests" if profile == "pytest" else ""
            value = str(target or default).strip()
            if not value:
                raise WorkbenchError(f"The {profile} profile requires a workspace-relative target.")
            resolved = self._resolve(value, require_exists=True)
            relative = self._relative(resolved)
        else:
            if target:
                raise WorkbenchError(f"The {profile} profile does not accept a target.")
            relative = ""
            resolved = self.root

        if profile == "python":
            if not resolved.is_file() or resolved.suffix.casefold() != ".py":
                raise WorkbenchError("The python profile requires an existing .py file.")
            executable = _python_executable()
            if not executable:
                raise WorkbenchError("Python is not installed or is not on PATH.")
            return [executable, relative], relative, False
        if profile == "python-compile":
            executable = _python_executable()
            if not executable:
                raise WorkbenchError("Python is not installed or is not on PATH.")
            return [executable, "-m", "compileall", "-q", relative], relative, True
        if profile == "pytest":
            executable = _python_executable()
            if not executable:
                raise WorkbenchError("Python is not installed or is not on PATH.")
            return [executable, "-m", "pytest", "-q", relative], relative, True
        if profile == "node":
            executable = shutil.which("node")
            if not executable:
                raise WorkbenchError("Node.js is not installed or is not on PATH.")
            if not resolved.is_file() or resolved.suffix.casefold() not in {".js", ".mjs", ".cjs"}:
                raise WorkbenchError("The node profile requires an existing .js, .mjs, or .cjs file.")
            return [executable, relative], relative, False
        executable = shutil.which("cargo")
        if not executable:
            raise WorkbenchError("Cargo is not installed or is not on PATH.")
        if not (self.root / "Cargo.toml").is_file():
            raise WorkbenchError("Cargo.toml was not found at the workspace root.")
        return [executable, "test"], "", True

    def _start_run(self, run_id: str, task_id: str, operation: str, payload: dict[str, Any]) -> None:
        self.events.create_run(run_id, task_id=task_id, total_steps=1, metadata={"authority": "EventStream", "operation": operation})
        self.events.emit_state_change(run_id, RunState.CREATED, task_id=task_id, operation=operation, **payload)
        self.events.emit(RunEvent(run_id=run_id, task_id=task_id, event_type="command.proposed", actor="developer.workbench", payload={"operation": operation, **payload}))
        self.events.emit_state_change(run_id, RunState.RUNNING, task_id=task_id, operation=operation)

    def _resolve(self, value: str, *, require_exists: bool) -> Path:
        text = str(value or ".").replace("\\", "/")
        pure = PurePosixPath(text)
        if pure.is_absolute() or ".." in pure.parts:
            raise WorkbenchError("Path must remain relative to the active workspace.")
        try:
            resolved = normalize_workspace_path(str(self.root), str(Path(*pure.parts)))
        except PermissionError as exc:
            raise WorkbenchError("Path escapes the active workspace.") from exc
        if require_exists and not resolved.exists():
            raise WorkbenchError(f"Workspace path does not exist: {text}")
        return resolved

    def _write_target(self, value: str) -> Path:
        target = self._resolve(value, require_exists=False)
        relative = PurePosixPath(self._relative(target))
        if not relative.parts or relative.as_posix() in {".", "workspace.json"}:
            raise WorkbenchError("This workspace-managed path cannot be written.")
        if relative.parts[0] in {".git", ".nous"}:
            raise WorkbenchError("Git and Nous metadata are protected.")
        if target.exists() and not target.is_file():
            raise WorkbenchError("The write target is not a file.")
        return target

    def _iter_files(self, root: Path) -> Iterable[Path]:
        scanned = 0
        for directory, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = sorted(
                (name for name in dirnames if name not in _IGNORED),
                key=str.casefold,
            )
            for filename in sorted(filenames, key=str.casefold):
                candidate = Path(directory) / filename
                scanned += 1
                if scanned > _MAX_SCAN_FILES:
                    return
                try:
                    resolved = candidate.resolve()
                    resolved.relative_to(self.root)
                except (OSError, ValueError):
                    continue
                if resolved.is_file():
                    yield resolved

    @staticmethod
    def _read_bytes(path: Path) -> bytes:
        size = path.stat().st_size
        if size > _MAX_READ_BYTES:
            raise WorkbenchError("The file exceeds the 512 KiB workbench read limit.")
        return path.read_bytes()

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    @staticmethod
    def _new_run_id(kind: str) -> str:
        return f"workbench-{kind}-{uuid4().hex[:16]}"

    @staticmethod
    def _display_argv(argv: list[str]) -> list[str]:
        return [Path(argv[0]).name, *argv[1:]]

    @staticmethod
    def _language(suffix: str) -> str:
        value = suffix.casefold()
        names = {".py": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".ts": "typescript", ".tsx": "typescript", ".rs": "rust", ".md": "markdown", ".json": "json", ".toml": "toml", ".yaml": "yaml", ".yml": "yaml"}
        return names.get(value, "text" if value in _CODE_SUFFIXES else "unknown")

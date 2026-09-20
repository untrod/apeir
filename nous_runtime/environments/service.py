"""Workspace-scoped governed Environment Runtime lifecycle service."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from uuid import uuid4

from nous_runtime.artifact import ArtifactManager, ArtifactRegistry, ArtifactType
from nous_runtime.environments.contract import CompatibilityHandshake
from nous_runtime.environments.models import (
    ALLOWED_TRANSITIONS,
    EnvironmentCommand,
    EnvironmentState,
    EnvironmentValidationError,
    ExecutionEnvironment,
)
from nous_runtime.environments.providers import (
    EnvironmentProviderError,
    EnvironmentProviderRegistry,
)
from nous_runtime.events import EventStream, RunEvent, RunState
from nous_runtime.locking import file_lock
from nous_runtime.project.workspace import default_workspace_path


class EnvironmentNotFoundError(EnvironmentValidationError):
    """The requested environment does not exist in the active workspace."""


class EnvironmentRuntime:
    """Canonical workspace authority for ExecutionEnvironment state and effects."""

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        providers: EnvironmentProviderRegistry | None = None,
    ) -> None:
        self.root = Path(workspace_root).expanduser().resolve()
        if not self.root.is_dir():
            raise EnvironmentValidationError("the active workspace does not exist")
        self.storage = self.root / ".nous" / "environments" / "records"
        self.outputs = self.root / "artifacts" / "environments"
        self.storage.mkdir(parents=True, exist_ok=True)
        self.providers = providers or EnvironmentProviderRegistry()
        self.events = EventStream(str(self.root))
        self.artifacts = ArtifactManager(
            ArtifactRegistry(self.root / ".nous" / "artifacts.jsonl")
        )
        self._handshakes: dict[str, CompatibilityHandshake] = {}
        for status in self.providers.status():
            provider = self.providers.get(str(status["provider_id"]))
            handshake = CompatibilityHandshake.for_provider(provider)
            handshake.require_compatible()
            self._handshakes[provider.provider_id] = handshake

    def status(self) -> dict[str, Any]:
        records = self.list_environments()
        return {
            "schema_version": "nous.environment-runtime/v1",
            "workspace": str(self.root),
            "environments": len(
                [item for item in records if item.get("state") != "invalid"]
            ),
            "providers": self.providers.status(),
            "compatibility": {
                key: value.to_dict() for key, value in sorted(self._handshakes.items())
            },
            "defaults": {
                "network": "none",
                "host_filesystem": "none",
                "privileged": False,
                "host_devices": "none",
                "engine_socket": "none",
                "host_pid": False,
                "host_network": False,
                "workspace_root": "/model-workspace",
            },
            "event_authority": "EventStream",
            "artifact_authority": "ArtifactRegistry",
            "state_authority": default_workspace_path("environments", "records").as_posix(),
        }

    def create(self, value: Mapping[str, Any]) -> dict[str, Any]:
        environment = ExecutionEnvironment.from_mapping(value, new_identity=True)
        provider = self.providers.get(environment.provider)
        provider_status = provider.probe()
        if (
            str(provider_status.get("environment_type") or "")
            != environment.environment_type.value
        ):
            raise EnvironmentValidationError(
                "provider does not support the requested environment_type"
            )
        handshake = CompatibilityHandshake.for_provider(provider)
        handshake.require_compatible()
        run_id = f"environment-create-{uuid4().hex}"
        task_id = (
            environment.task_id or f"environment.create:{environment.environment_id}"
        )
        self._start_run(
            run_id,
            task_id,
            "environment.create",
            {
                "environment_id": environment.environment_id,
                "provider": environment.provider,
                "environment_type": environment.environment_type.value,
            },
        )
        try:
            path = self._environment_path(environment.environment_id)
            self._write_environment(path, environment)
            artifact = self.artifacts.create(
                ArtifactType.FILE,
                f"Environment Contract: {environment.environment_id}",
                location=path.relative_to(self.root).as_posix(),
                creator="environment.runtime",
                metadata={
                    "environment_id": environment.environment_id,
                    "format": "environment-contract",
                    "sha256": environment.digest(),
                    "schema_version": environment.schema_version,
                    "provider": environment.provider,
                },
            )
            self._emit(
                run_id,
                task_id,
                "environment.created",
                {
                    "environment_id": environment.environment_id,
                    "state": environment.state.value,
                    "provider": environment.provider,
                    "sha256": environment.digest(),
                },
            )
            self._artifact_event(run_id, task_id, artifact, environment.environment_id)
            self.events.emit_state_change(
                run_id,
                RunState.COMPLETED,
                task_id=task_id,
                environment_id=environment.environment_id,
                artifact_id=artifact.id,
            )
            return {
                **environment.to_dict(),
                "sha256": environment.digest(),
                "artifact_id": artifact.id,
                "operation_run_id": run_id,
                "compatibility": handshake.to_dict(),
            }
        except Exception as exc:
            self.events.emit_state_change(
                run_id,
                RunState.FAILED,
                task_id=task_id,
                environment_id=environment.environment_id,
                error=str(exc),
            )
            raise

    def get(self, environment_id: str) -> dict[str, Any]:
        environment = self._load(environment_id)
        return {
            **environment.to_dict(),
            "sha256": environment.digest(),
            "expired": _is_expired(environment),
        }

    def list_environments(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(
            self.storage.glob("env_*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            try:
                environment = self._read_environment(path)
                records.append(
                    {
                        **environment.to_dict(),
                        "sha256": environment.digest(),
                        "expired": _is_expired(environment),
                    }
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                records.append(
                    {
                        "environment_id": path.stem,
                        "state": "invalid",
                        "error": "Environment Contract integrity validation failed",
                    }
                )
        return records

    def start(self, environment_id: str) -> dict[str, Any]:
        environment = self._load(environment_id)
        if _is_expired(environment):
            raise EnvironmentValidationError("environment lifetime has expired")
        if environment.state not in {
            EnvironmentState.CREATED,
            EnvironmentState.STOPPED,
            EnvironmentState.FAILED,
        }:
            raise EnvironmentValidationError(
                f"environment cannot start from state {environment.state.value}"
            )
        run_id = f"environment-start-{uuid4().hex}"
        task_id = (
            environment.task_id or f"environment.start:{environment.environment_id}"
        )
        self._start_run(
            run_id,
            task_id,
            "environment.start",
            {"environment_id": environment.environment_id},
        )
        provider = self.providers.get(environment.provider)
        handle = environment.provider_handle
        try:
            environment = self._transition(
                environment, EnvironmentState.PREPARING, run_id, task_id
            )
            if not handle:
                handle = provider.prepare(environment, self.root)
            provider.start(environment, handle)
            environment = self._transition(
                environment,
                EnvironmentState.READY,
                run_id,
                task_id,
                provider_handle=handle,
                last_error="",
            )
            self._emit(
                run_id,
                task_id,
                "environment.started",
                {
                    "environment_id": environment.environment_id,
                    "provider": environment.provider,
                    "state": environment.state.value,
                },
            )
            self.events.emit_state_change(
                run_id,
                RunState.COMPLETED,
                task_id=task_id,
                environment_id=environment.environment_id,
            )
            return {
                **environment.to_dict(),
                "sha256": environment.digest(),
                "operation_run_id": run_id,
            }
        except Exception as exc:
            self._fail_environment(
                environment, str(exc), run_id, task_id, provider_handle=handle
            )
            raise

    def run(self, environment_id: str, value: Mapping[str, Any]) -> dict[str, Any]:
        environment = self._load(environment_id)
        if _is_expired(environment):
            raise EnvironmentValidationError("environment lifetime has expired")
        if environment.state is not EnvironmentState.READY:
            raise EnvironmentValidationError(
                f"environment must be ready before execution; found {environment.state.value}"
            )
        command = EnvironmentCommand.from_mapping(value)
        run_id = f"environment-run-{uuid4().hex}"
        task_id = environment.task_id or f"environment.run:{environment.environment_id}"
        self._start_run(
            run_id,
            task_id,
            "environment.run",
            {
                "environment_id": environment.environment_id,
                "argv": list(command.argv),
                "cwd": command.cwd,
            },
        )
        provider = self.providers.get(environment.provider)
        try:
            environment = self._transition(
                environment, EnvironmentState.RUNNING, run_id, task_id
            )
            self._emit(
                run_id,
                task_id,
                "command.started",
                {
                    "environment_id": environment.environment_id,
                    "argv": list(command.argv),
                    "cwd": command.cwd,
                    "timeout_seconds": command.timeout_seconds,
                    "environment_variable_names": sorted(command.env),
                },
            )
            result = provider.execute(environment, environment.provider_handle, command)
            output = self._write_run_artifact(
                environment, run_id, command, result.to_dict()
            )
            artifact = self.artifacts.create(
                ArtifactType.FILE,
                f"Environment Run: {environment.environment_id}",
                location=output["location"],
                creator="environment.runtime",
                metadata={
                    "environment_id": environment.environment_id,
                    "run_id": run_id,
                    "sha256": output["sha256"],
                    "size_bytes": output["size_bytes"],
                    "exit_code": result.exit_code,
                    "ok": result.ok,
                    "provider": environment.provider,
                },
            )
            for stream_name, text in (
                ("stdout", result.stdout),
                ("stderr", result.stderr),
            ):
                if text:
                    self.events.emit_chunked(
                        RunEvent(
                            run_id=run_id,
                            task_id=task_id,
                            event_type="command.output",
                            actor="environment.runtime",
                            payload={
                                "environment_id": environment.environment_id,
                                "stream": stream_name,
                                "text": text,
                            },
                        )
                    )
            self._artifact_event(run_id, task_id, artifact, environment.environment_id)
            environment = self._transition(
                environment,
                EnvironmentState.READY,
                run_id,
                task_id,
                last_error=""
                if result.ok
                else f"command exited with code {result.exit_code}",
            )
            final_state = RunState.COMPLETED if result.ok else RunState.FAILED
            self.events.emit_state_change(
                run_id,
                final_state,
                task_id=task_id,
                environment_id=environment.environment_id,
                exit_code=result.exit_code,
                artifact_id=artifact.id,
                timed_out=result.timed_out,
            )
            return {
                "environment_id": environment.environment_id,
                "state": environment.state.value,
                "operation_run_id": run_id,
                "artifact_id": artifact.id,
                "artifact": output,
                **result.to_dict(),
            }
        except Exception as exc:
            self._fail_environment(environment, str(exc), run_id, task_id)
            raise

    def stop(self, environment_id: str) -> dict[str, Any]:
        environment = self._load(environment_id)
        if _is_expired(environment):
            raise EnvironmentValidationError("environment lifetime has expired")
        if environment.state not in {
            EnvironmentState.READY,
            EnvironmentState.RUNNING,
            EnvironmentState.SUSPENDED,
        }:
            raise EnvironmentValidationError(
                f"environment cannot stop from state {environment.state.value}"
            )
        run_id = f"environment-stop-{uuid4().hex}"
        task_id = (
            environment.task_id or f"environment.stop:{environment.environment_id}"
        )
        self._start_run(
            run_id,
            task_id,
            "environment.stop",
            {"environment_id": environment.environment_id},
        )
        provider = self.providers.get(environment.provider)
        try:
            environment = self._transition(
                environment, EnvironmentState.STOPPING, run_id, task_id
            )
            provider.stop(environment, environment.provider_handle)
            environment = self._transition(
                environment, EnvironmentState.STOPPED, run_id, task_id
            )
            self.events.emit_state_change(
                run_id,
                RunState.COMPLETED,
                task_id=task_id,
                environment_id=environment.environment_id,
            )
            return {
                **environment.to_dict(),
                "sha256": environment.digest(),
                "operation_run_id": run_id,
            }
        except Exception as exc:
            self._fail_environment(environment, str(exc), run_id, task_id)
            raise

    def destroy(self, environment_id: str) -> dict[str, Any]:
        environment = self._load(environment_id)
        if environment.state is EnvironmentState.DESTROYED:
            raise EnvironmentValidationError("environment is already destroyed")
        run_id = f"environment-destroy-{uuid4().hex}"
        task_id = (
            environment.task_id or f"environment.destroy:{environment.environment_id}"
        )
        self._start_run(
            run_id,
            task_id,
            "environment.destroy",
            {"environment_id": environment.environment_id},
        )
        provider = self.providers.get(environment.provider)
        try:
            if environment.state in {
                EnvironmentState.READY,
                EnvironmentState.RUNNING,
                EnvironmentState.SUSPENDED,
            }:
                environment = self._transition(
                    environment, EnvironmentState.STOPPING, run_id, task_id
                )
                provider.stop(environment, environment.provider_handle)
                environment = self._transition(
                    environment, EnvironmentState.STOPPED, run_id, task_id
                )
            if environment.provider_handle:
                provider.destroy(environment, environment.provider_handle)
            environment = self._transition(
                environment,
                EnvironmentState.DESTROYED,
                run_id,
                task_id,
                provider_handle="",
            )

            self.events.emit_state_change(
                run_id,
                RunState.COMPLETED,
                task_id=task_id,
                environment_id=environment.environment_id,
            )
            return {
                **environment.to_dict(),
                "sha256": environment.digest(),
                "operation_run_id": run_id,
            }
        except Exception as exc:
            self._fail_environment(environment, str(exc), run_id, task_id)
            raise

    def logs(self, environment_id: str) -> dict[str, Any]:
        environment = self._load(environment_id)
        provider = self.providers.get(environment.provider)
        text = provider.logs(environment, environment.provider_handle)
        if len(text.encode("utf-8")) > 2_000_000:
            text = text[-2_000_000:]
        return {
            "environment_id": environment.environment_id,
            "provider": environment.provider,
            "state": environment.state.value,
            "text": text,
        }

    def stage_file(
        self,
        environment_id: str,
        relative_path: str,
        content: bytes,
        *,
        max_bytes: int = 16_000_000,
    ) -> dict[str, Any]:
        """Stage a bounded Runtime-owned input inside a local Environment workdir."""
        environment = self._load(environment_id)
        if environment.state not in {EnvironmentState.READY, EnvironmentState.RUNNING}:
            raise EnvironmentValidationError(
                "environment must be ready or running for file staging"
            )
        if environment.provider != "local-sandbox":
            raise EnvironmentProviderError(
                "provider does not support Runtime file staging"
            )
        if not isinstance(content, bytes) or len(content) > max(
            1, min(int(max_bytes), 16_000_000)
        ):
            raise EnvironmentValidationError("staged content exceeds its bounded size")
        root = Path(environment.provider_handle).resolve()
        if "\\" in str(relative_path or ""):
            raise EnvironmentValidationError("staged path must use forward slashes")
        relative = PurePosixPath(str(relative_path or ""))
        if not relative.parts or relative.is_absolute() or ".." in relative.parts:
            raise EnvironmentValidationError("staged path must be environment-relative")
        target = (root / Path(*relative.parts)).resolve()
        if not _is_below(root, target):
            raise EnvironmentValidationError("staged path escaped the environment")
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".nous-stage-", dir=target.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return {
            "relative_path": relative.as_posix(),
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }

    def read_file(
        self,
        environment_id: str,
        relative_path: str,
        *,
        max_bytes: int = 50_000_000,
    ) -> bytes:
        """Collect one bounded output from a local Environment workdir."""
        environment = self._load(environment_id)
        if environment.state not in {EnvironmentState.READY, EnvironmentState.RUNNING}:
            raise EnvironmentValidationError(
                "environment must be ready or running for file collection"
            )
        if environment.provider != "local-sandbox":
            raise EnvironmentProviderError(
                "provider does not support Runtime file collection"
            )
        root = Path(environment.provider_handle).resolve()
        if "\\" in str(relative_path or ""):
            raise EnvironmentValidationError("collected path must use forward slashes")
        relative = PurePosixPath(str(relative_path or ""))
        if not relative.parts or relative.is_absolute() or ".." in relative.parts:
            raise EnvironmentValidationError(
                "collected path must be environment-relative"
            )
        target = (root / Path(*relative.parts)).resolve()
        if not _is_below(root, target) or not target.is_file() or target.is_symlink():
            raise EnvironmentValidationError(
                "collected Environment output is unavailable"
            )
        limit = max(1, min(int(max_bytes), 50_000_000))
        if target.stat().st_size > limit:
            raise EnvironmentValidationError(
                "collected Environment output exceeds its bounded size"
            )
        return target.read_bytes()

    def _transition(
        self,
        environment: ExecutionEnvironment,
        target: EnvironmentState,
        run_id: str,
        task_id: str,
        **changes: Any,
    ) -> ExecutionEnvironment:
        previous = environment.state
        next_environment = environment.transition(target, **changes)
        self._write_environment(
            self._environment_path(environment.environment_id), next_environment
        )
        self._emit(
            run_id,
            task_id,
            f"environment.{target.value}",
            {
                "environment_id": environment.environment_id,
                "previous_state": previous.value,
                "state": target.value,
                "provider": environment.provider,
            },
        )
        return next_environment

    def _fail_environment(
        self,
        environment: ExecutionEnvironment,
        error: str,
        run_id: str,
        task_id: str,
        **changes: Any,
    ) -> None:
        try:
            if (
                environment.state is not EnvironmentState.FAILED
                and EnvironmentState.FAILED in ALLOWED_TRANSITIONS[environment.state]
            ):
                environment = self._transition(
                    environment,
                    EnvironmentState.FAILED,
                    run_id,
                    task_id,
                    last_error=error[:2048],
                    **changes,
                )
        finally:
            self.events.emit_state_change(
                run_id,
                RunState.FAILED,
                task_id=task_id,
                environment_id=environment.environment_id,
                error=error,
            )

    def _environment_path(self, environment_id: str) -> Path:
        if not re.fullmatch(r"env_[a-f0-9]{32}", str(environment_id)):
            raise EnvironmentValidationError("environment_id is invalid")
        target = (self.storage / f"{environment_id}.json").resolve()
        if target.parent != self.storage.resolve():
            raise EnvironmentValidationError("environment path escaped storage")
        return target

    def _load(self, environment_id: str) -> ExecutionEnvironment:
        path = self._environment_path(environment_id)
        if not path.is_file():
            raise EnvironmentNotFoundError(f"environment not found: {environment_id}")
        return self._read_environment(path)

    @staticmethod
    def _read_environment(path: Path) -> ExecutionEnvironment:
        with file_lock(str(path) + ".lock"):
            payload = json.loads(path.read_text(encoding="utf-8"))
        expected = str(payload.pop("sha256", ""))
        environment = ExecutionEnvironment.from_mapping(payload)
        if not expected or expected != environment.digest():
            raise EnvironmentValidationError(
                "Environment Contract integrity digest mismatch"
            )
        return environment

    @staticmethod
    def _write_environment(path: Path, environment: ExecutionEnvironment) -> None:
        value = {**environment.to_dict(), "sha256": environment.digest()}
        EnvironmentRuntime._atomic_json(path, value)

    @staticmethod
    def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        with file_lock(str(path) + ".lock"):
            descriptor, temporary = tempfile.mkstemp(
                prefix=".nous-environment-", suffix=".json", dir=path.parent
            )
            try:
                with os.fdopen(
                    descriptor, "w", encoding="utf-8", newline="\n"
                ) as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    def _write_run_artifact(
        self,
        environment: ExecutionEnvironment,
        run_id: str,
        command: EnvironmentCommand,
        result: Mapping[str, Any],
    ) -> dict[str, Any]:
        target = (
            self.outputs / environment.environment_id / f"{run_id}.json"
        ).resolve()
        if not _is_below(self.outputs.resolve(), target):
            raise EnvironmentValidationError(
                "environment run artifact escaped output storage"
            )
        value = {
            "schema_version": "nous.environment-run/v1",
            "environment_id": environment.environment_id,
            "provider": environment.provider,
            "environment_contract_sha256": environment.digest(),
            "command": {
                "argv": list(command.argv),
                "cwd": command.cwd,
                "timeout_seconds": command.timeout_seconds,
                "max_output_bytes": command.max_output_bytes,
                "environment_variable_names": sorted(command.env),
            },
            "result": dict(result),
        }
        self._atomic_json(target, value)
        encoded = target.read_bytes()
        return {
            "location": target.relative_to(self.root).as_posix(),
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "size_bytes": len(encoded),
        }

    def _start_run(
        self,
        run_id: str,
        task_id: str,
        operation: str,
        metadata: Mapping[str, Any],
    ) -> None:
        self.events.create_run(
            run_id,
            task_id=task_id,
            total_steps=1,
            metadata={
                "authority": "EventStream",
                "operation": operation,
                **dict(metadata),
            },
        )
        self.events.emit_state_change(
            run_id,
            RunState.CREATED,
            task_id=task_id,
            operation=operation,
            **dict(metadata),
        )
        self._emit(
            run_id,
            task_id,
            "command.proposed",
            {"operation": operation, **dict(metadata)},
        )
        self.events.emit_state_change(
            run_id, RunState.RUNNING, task_id=task_id, operation=operation
        )

    def _emit(
        self,
        run_id: str,
        task_id: str,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> None:
        self.events.emit(
            RunEvent(
                run_id=run_id,
                task_id=task_id,
                event_type=event_type,
                actor="environment.runtime",
                payload=dict(payload),
            )
        )

    def _artifact_event(
        self, run_id: str, task_id: str, artifact, environment_id: str
    ) -> None:
        self._emit(
            run_id,
            task_id,
            "artifact.created",
            {
                "artifact_id": artifact.id,
                "artifact_type": artifact.type,
                "location": artifact.location,
                "environment_id": environment_id,
            },
        )


def _is_expired(environment: ExecutionEnvironment) -> bool:
    try:
        created = datetime.fromisoformat(environment.created_at.replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return (
        datetime.now(timezone.utc) - created
    ).total_seconds() >= environment.lifetime_seconds


def _is_below(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


__all__ = ["EnvironmentNotFoundError", "EnvironmentRuntime"]

"""Durable ProcessSession tools over the detached kernel process host."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from nous_runtime.artifact import ArtifactType, ContentAddressedArtifactStore
from nous_runtime.events import EventStream, RunEvent
from nous_runtime.kernel.process_session_host import (
    ProcessSandboxHost,
    process_identity_matches,
)
from nous_runtime.locking import file_lock

if TYPE_CHECKING:
    from nous_runtime.chat.agent_tools import WorkspaceToolRuntime


_TERMINAL_STATES = {"EXITED", "INTERRUPTED", "TERMINATED", "KILLED"}
_MAX_READ_BYTES = 64 * 1024
_MAX_EVENT_CHUNKS = 32
_EVENT_EXCERPT_BYTES = 4 * 1024
_MAX_STDIN_BYTES = 64 * 1024


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{uuid4().hex}.tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(dict(value), handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class ProcessSessionState(str, Enum):
    PENDING = "PENDING"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    EXITED = "EXITED"
    INTERRUPTED = "INTERRUPTED"
    TERMINATED = "TERMINATED"
    KILLED = "KILLED"
    LOST = "LOST"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


@dataclass
class ProcessSession:
    session_id: str
    work_id: str
    tool_call_id: str
    command: list[str]
    cwd: str
    environment_ref: str
    command_digest: str
    state: str = ProcessSessionState.PENDING.value
    process_identity: dict[str, Any] = field(default_factory=dict)
    helper_identity: dict[str, Any] = field(default_factory=dict)
    started_at: str = ""
    updated_at: str = field(default_factory=_utc_now)
    completed_at: str = ""
    exit_code: int | None = None
    stdout_cursor: int = 0
    stderr_cursor: int = 0
    stdin_available: bool = False
    action_sequence: int = 0
    output_event_count: int = 0
    artifacts: dict[str, str] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "nous.process-session/v1",
            **asdict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProcessSession:
        if value.get("schema") != "nous.process-session/v1":
            raise ValueError("unsupported process session schema")
        state = str(value.get("state") or "")
        ProcessSessionState(state)
        return cls(
            session_id=str(value.get("session_id") or ""),
            work_id=str(value.get("work_id") or ""),
            tool_call_id=str(value.get("tool_call_id") or ""),
            command=[str(item) for item in value.get("command") or ()],
            cwd=str(value.get("cwd") or ""),
            environment_ref=str(value.get("environment_ref") or ""),
            command_digest=str(value.get("command_digest") or ""),
            state=state,
            process_identity=dict(value.get("process_identity") or {}),
            helper_identity=dict(value.get("helper_identity") or {}),
            started_at=str(value.get("started_at") or ""),
            updated_at=str(value.get("updated_at") or ""),
            completed_at=str(value.get("completed_at") or ""),
            exit_code=(
                int(value["exit_code"]) if value.get("exit_code") is not None else None
            ),
            stdout_cursor=int(value.get("stdout_cursor") or 0),
            stderr_cursor=int(value.get("stderr_cursor") or 0),
            stdin_available=bool(value.get("stdin_available", False)),
            action_sequence=int(value.get("action_sequence") or 0),
            output_event_count=int(value.get("output_event_count") or 0),
            artifacts={
                str(key): str(item)
                for key, item in dict(value.get("artifacts") or {}).items()
            },
            error=str(value.get("error") or ""),
        )


class ProcessSessionStore:
    """Durable session facts and reconnectable controls for one workspace."""

    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace).expanduser().resolve(strict=True)
        self.root = self.workspace / ".nous" / "process-sessions"
        self.root.mkdir(parents=True, exist_ok=True)
        self.events = EventStream(str(self.workspace))
        self.artifacts = ContentAddressedArtifactStore(
            self.workspace / ".nous" / "artifacts"
        )

    def start(
        self,
        command: list[str],
        *,
        cwd: str | Path,
        environment: Mapping[str, str],
        work_id: str = "",
        tool_call_id: str = "",
        action_sequence: int = 0,
    ) -> dict[str, Any]:
        if not command:
            raise ValueError("process command is required")
        session_id = f"ps_{uuid4().hex}"
        directory = self.root / session_id
        directory.mkdir(parents=True)
        resolved_cwd = Path(cwd).resolve(strict=True)
        try:
            resolved_cwd.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("process cwd must remain inside the workspace") from exc
        command_digest = _digest(command)
        session = ProcessSession(
            session_id=session_id,
            work_id=str(work_id or ""),
            tool_call_id=str(tool_call_id or ""),
            command=list(command),
            cwd=str(resolved_cwd),
            environment_ref=_digest(dict(environment)),
            command_digest=command_digest,
            action_sequence=int(action_sequence or 0),
        )
        self._save(session)  # durable dispatch fact
        self._emit(session, "process.dispatch.persisted")
        session.state = ProcessSessionState.STARTING.value
        session.updated_at = _utc_now()
        self._save(session)  # durable start intent before spawn
        self._emit(session, "process.starting")
        spec = {
            "schema": "nous.process-host/v1",
            "session_id": session_id,
            "command": list(command),
            "command_digest": command_digest,
            "cwd": str(resolved_cwd),
            "env": {str(key): str(value) for key, value in environment.items()},
        }
        _atomic_json(directory / "spec.json", spec)
        try:
            session.helper_identity = ProcessSandboxHost.launch(directory / "spec.json")
            session.updated_at = _utc_now()
            self._save(session)
        except (OSError, RuntimeError, ValueError) as exc:
            session.state = ProcessSessionState.RECOVERY_REQUIRED.value
            session.error = str(exc)
            session.updated_at = _utc_now()
            self._save(session)
            self._emit(session, "process.recovery.required")
            return self._result(session)

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            host = self._host_state(session_id)
            if host.get("state") not in {None, "", "STARTING"}:
                return self.status(session_id)
            time.sleep(0.025)
        session.state = ProcessSessionState.RECOVERY_REQUIRED.value
        session.error = "process spawn outcome is not yet provable"
        session.updated_at = _utc_now()
        self._save(session)
        self._emit(session, "process.recovery.required")
        return self._result(session)

    def status(self, session_id: str) -> dict[str, Any]:
        session = self.require(session_id)
        previous = session.state
        host = self._host_state(session.session_id)
        if host:
            self._merge_host_state(session, host)
        elif session.state in {
            ProcessSessionState.PENDING.value,
            ProcessSessionState.STARTING.value,
            ProcessSessionState.RUNNING.value,
        }:
            session.state = ProcessSessionState.RECOVERY_REQUIRED.value
            session.stdin_available = False
            session.error = "process host state is missing"
            session.updated_at = _utc_now()
        if session.state in _TERMINAL_STATES:
            self._materialize_logs(session)
        self._save(session)
        if previous != session.state:
            self._emit(session, f"process.{session.state.casefold()}")
        return self._result(session)

    def attach(self, session_id: str) -> dict[str, Any]:
        result = self.status(session_id)
        session = self.require(session_id)
        self._emit(session, "process.attached")
        return {**result, "attached": True}

    def detach(self, session_id: str) -> dict[str, Any]:
        result = self.status(session_id)
        session = self.require(session_id)
        self._emit(session, "process.detached")
        return {**result, "attached": False}

    def read_output(
        self,
        session_id: str,
        stream: str,
        *,
        cursor: int | None = None,
        limit: int = _MAX_READ_BYTES,
    ) -> dict[str, Any]:
        if stream not in {"stdout", "stderr"}:
            raise ValueError("stream must be stdout or stderr")
        session = self.require(session_id)
        self.status(session_id)
        session = self.require(session_id)
        selected_cursor = (
            int(cursor)
            if cursor is not None
            else int(getattr(session, f"{stream}_cursor"))
        )
        selected_cursor = max(0, selected_cursor)
        maximum = max(1, min(int(limit), _MAX_READ_BYTES))
        path = self._directory(session_id) / f"{stream}.log"
        size = path.stat().st_size if path.is_file() else 0
        if selected_cursor > size:
            raise ValueError("output cursor is beyond the current spool")
        data = b""
        if path.is_file():
            with path.open("rb") as handle:
                handle.seek(selected_cursor)
                data = handle.read(maximum)
        next_cursor = selected_cursor + len(data)
        setattr(session, f"{stream}_cursor", next_cursor)
        if data and session.output_event_count < _MAX_EVENT_CHUNKS:
            excerpt = data[:_EVENT_EXCERPT_BYTES].decode("utf-8", errors="replace")
            self.events.emit_chunked(
                RunEvent(
                    run_id=self._event_run_id(session),
                    task_id=session.tool_call_id,
                    event_type="command.output",
                    actor="process-session",
                    payload={
                        "session_id": session.session_id,
                        "stream": stream,
                        "cursor": selected_cursor,
                        "next_cursor": next_cursor,
                        "text": excerpt,
                        "excerpt": len(data) > len(data[:_EVENT_EXCERPT_BYTES]),
                    },
                )
            )
            session.output_event_count += 1
        session.updated_at = _utc_now()
        self._save(session)
        return {
            "ok": True,
            "session_id": session_id,
            "stream": stream,
            "cursor": selected_cursor,
            "next_cursor": next_cursor,
            "size_bytes": size,
            "eof": next_cursor >= size and session.state in _TERMINAL_STATES,
            "text": data.decode("utf-8", errors="replace"),
            "truncated": next_cursor < size,
            "state": session.state,
        }

    def write_stdin(self, session_id: str, data: str) -> dict[str, Any]:
        encoded = str(data).encode("utf-8")
        if len(encoded) > _MAX_STDIN_BYTES:
            raise ValueError("stdin payload exceeds 64 KiB")
        return self._control(
            session_id,
            "stdin",
            data_base64=base64.b64encode(encoded).decode("ascii"),
        )

    def close_stdin(self, session_id: str) -> dict[str, Any]:
        return self._control(session_id, "close_stdin")

    def interrupt(self, session_id: str) -> dict[str, Any]:
        return self._control(session_id, "interrupt")

    def terminate(self, session_id: str) -> dict[str, Any]:
        return self._control(session_id, "terminate")

    def kill(self, session_id: str) -> dict[str, Any]:
        return self._control(session_id, "kill")

    def recover(
        self,
        *,
        session_id: str = "",
        work_id: str = "",
        action_sequence: int = 0,
    ) -> dict[str, Any]:
        matches = []
        if session_id:
            matches = [self.require(session_id)]
        else:
            for path in self.root.glob("ps_*/session.json"):
                try:
                    candidate = ProcessSession.from_dict(
                        json.loads(path.read_text(encoding="utf-8"))
                    )
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                if work_id and candidate.work_id != work_id:
                    continue
                if action_sequence and candidate.action_sequence != action_sequence:
                    continue
                matches.append(candidate)
        if len(matches) != 1:
            return {
                "ok": False,
                "found": False,
                "recovery_required": True,
                "error": "a unique process session could not be proven",
                "match_count": len(matches),
            }
        result = self.status(matches[0].session_id)
        return {
            **result,
            "found": True,
            "recovery_required": result["state"]
            in {
                ProcessSessionState.LOST.value,
                ProcessSessionState.RECOVERY_REQUIRED.value,
            },
            "automatic_replay": False,
        }

    def require(self, session_id: str) -> ProcessSession:
        path = self._directory(session_id) / "session.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError(f"process session not found: {session_id}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"process session state is unreadable: {session_id}"
            ) from exc
        if not isinstance(value, Mapping):
            raise TypeError("process session state must be an object")
        session = ProcessSession.from_dict(value)
        if session.session_id != session_id:
            raise ValueError("process session identity mismatch")
        if _digest(session.command) != session.command_digest:
            raise ValueError("process session command digest mismatch")
        return session

    def _merge_host_state(
        self, session: ProcessSession, host: Mapping[str, Any]
    ) -> None:
        if (
            str(host.get("session_id") or "") != session.session_id
            or str(host.get("command_digest") or "") != session.command_digest
        ):
            session.state = ProcessSessionState.RECOVERY_REQUIRED.value
            session.error = "process host binding mismatch"
            session.stdin_available = False
            return
        identity = dict(host.get("process_identity") or {})
        helper_identity = dict(host.get("helper_identity") or {})
        expected_helper_digest = (
            "sha256:"
            + hashlib.sha256(
                str(
                    (self._directory(session.session_id) / "spec.json").resolve()
                ).encode("utf-8")
            ).hexdigest()
        )
        if (
            not helper_identity
            or str(helper_identity.get("command_digest") or "")
            != expected_helper_digest
            or (session.helper_identity and session.helper_identity != helper_identity)
        ):
            session.state = ProcessSessionState.RECOVERY_REQUIRED.value
            session.error = "process helper identity changed"
            session.stdin_available = False
            return
        if not session.helper_identity:
            session.helper_identity = helper_identity
        if identity:
            if str(identity.get("command_digest") or "") != session.command_digest:
                session.state = ProcessSessionState.RECOVERY_REQUIRED.value
                session.error = "process command binding mismatch"
                session.stdin_available = False
                return
            if session.process_identity and session.process_identity != identity:
                session.state = ProcessSessionState.RECOVERY_REQUIRED.value
                session.error = "process identity changed"
                session.stdin_available = False
                return
            if not session.process_identity:
                session.process_identity = identity
        host_state = str(host.get("state") or "")
        try:
            ProcessSessionState(host_state)
        except ValueError:
            session.state = ProcessSessionState.RECOVERY_REQUIRED.value
            session.error = "process host returned an invalid state"
            session.stdin_available = False
            return
        if host_state == ProcessSessionState.RUNNING.value:
            if (
                not identity
                or not process_identity_matches(identity)
                or not process_identity_matches(session.helper_identity)
            ):
                session.state = ProcessSessionState.RECOVERY_REQUIRED.value
                session.error = "running process host identity cannot be verified"
                session.stdin_available = False
                return
        elif host_state in _TERMINAL_STATES and (
            not identity or identity != session.process_identity
        ):
            session.state = ProcessSessionState.RECOVERY_REQUIRED.value
            session.error = "terminal observation is not bound to the process identity"
            session.stdin_available = False
            return
        session.state = host_state
        session.started_at = str(host.get("started_at") or session.started_at)
        session.updated_at = str(host.get("updated_at") or _utc_now())
        session.completed_at = str(host.get("completed_at") or session.completed_at)
        session.exit_code = (
            int(host["exit_code"])
            if host.get("exit_code") is not None
            else session.exit_code
        )
        session.stdin_available = bool(host.get("stdin_available", False))
        session.error = str(host.get("error") or "")

    def _control(self, session_id: str, action: str, **payload: Any) -> dict[str, Any]:
        status = self.status(session_id)
        if status["state"] != ProcessSessionState.RUNNING.value:
            raise ValueError(f"process session is not running: {status['state']}")
        directory = self._directory(session_id)
        control_id = f"ctl_{time.time_ns()}_{uuid4().hex[:8]}"
        request = {
            "schema": "nous.process-control/v1",
            "control_id": control_id,
            "session_id": session_id,
            "action": action,
            "created_at": _utc_now(),
            **payload,
        }
        _atomic_json(directory / "control" / f"{control_id}.json", request)
        deadline = time.monotonic() + 5.0
        ack_path = directory / "ack" / f"{control_id}.json"
        while time.monotonic() < deadline:
            if ack_path.is_file():
                ack = json.loads(ack_path.read_text(encoding="utf-8"))
                if not bool(ack.get("ok")):
                    raise RuntimeError(
                        str(ack.get("error") or "process control failed")
                    )
                session = self.require(session_id)
                self._emit(session, f"process.{action}.requested")
                return {
                    "ok": True,
                    "session_id": session_id,
                    "action": action,
                    "state": self.status(session_id)["state"],
                }
            time.sleep(0.025)
        raise RuntimeError("process host did not acknowledge the control request")

    def _materialize_logs(self, session: ProcessSession) -> None:
        for stream in ("stdout", "stderr"):
            if stream in session.artifacts:
                continue
            path = self._directory(session.session_id) / f"{stream}.log"
            if not path.is_file():
                continue
            stored = self.artifacts.store_file(
                path,
                artifact_type=ArtifactType.EVIDENCE,
                name=f"{session.session_id}-{stream}.log",
                media_type="text/plain; charset=utf-8",
                produced_by="process-session",
                metadata={
                    "schema": "nous.process-log/v1",
                    "session_id": session.session_id,
                    "work_id": session.work_id,
                    "tool_call_id": session.tool_call_id,
                    "stream": stream,
                    "command_digest": session.command_digest,
                    "exit_code": session.exit_code,
                },
            )
            digest = str(stored["artifact"]["digest"])
            self.artifacts.pin(digest, reason=f"process-session:{session.session_id}")
            session.artifacts[stream] = digest
            self._emit(
                session,
                "artifact.created",
                {"stream": stream, "artifact_ref": digest},
            )

    def _save(self, session: ProcessSession) -> None:
        session.updated_at = session.updated_at or _utc_now()
        path = self._directory(session.session_id) / "session.json"
        with file_lock(str(path) + ".lock"):
            _atomic_json(path, session.to_dict())

    def _host_state(self, session_id: str) -> dict[str, Any]:
        path = self._directory(session_id) / "host.json"
        if not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return dict(value) if isinstance(value, Mapping) else {}

    def _directory(self, session_id: str) -> Path:
        if not session_id.startswith("ps_") or not session_id[3:].isalnum():
            raise ValueError("invalid process session id")
        return self.root / session_id

    def _emit(
        self,
        session: ProcessSession,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        self.events.emit(
            RunEvent(
                run_id=self._event_run_id(session),
                task_id=session.tool_call_id,
                event_type=event_type,
                actor="process-session",
                payload={
                    "session_id": session.session_id,
                    "state": session.state,
                    **dict(payload or {}),
                },
            )
        )

    @staticmethod
    def _event_run_id(session: ProcessSession) -> str:
        return session.work_id or f"process.{session.session_id}"

    @staticmethod
    def _result(session: ProcessSession) -> dict[str, Any]:
        return {
            "ok": session.state not in {"LOST", "RECOVERY_REQUIRED"},
            **session.to_dict(),
        }


class ProcessSessionToolRuntime:
    """Model-facing tool adapter; authorization remains in WorkspaceToolRuntime."""

    def __init__(self, workspace_runtime: WorkspaceToolRuntime):
        self.workspace_runtime = workspace_runtime
        self.store = ProcessSessionStore(workspace_runtime.root)

    def specifications(self) -> tuple[dict[str, Any], ...]:
        identifier = {"type": "string", "minLength": 1}
        cursor = {"type": "integer", "minimum": 0}
        return (
            self._tool(
                "shell_start",
                "Start a governed persistent development process and return its session id.",
                {
                    "command": {
                        "oneOf": [
                            {"type": "array", "items": {"type": "string"}},
                            {"type": "string"},
                        ]
                    },
                    "cwd": {"type": "string"},
                },
                ("command",),
            ),
            self._tool(
                "shell_status",
                "Inspect a persistent process session.",
                {"session_id": identifier},
                ("session_id",),
            ),
            self._tool(
                "shell_attach",
                "Attach to a persistent process session without replaying it.",
                {"session_id": identifier},
                ("session_id",),
            ),
            self._tool(
                "shell_detach",
                "Detach while leaving a persistent process running.",
                {"session_id": identifier},
                ("session_id",),
            ),
            self._tool(
                "shell_stdout",
                "Read bounded stdout bytes from a cursor.",
                {
                    "session_id": identifier,
                    "cursor": cursor,
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": _MAX_READ_BYTES,
                    },
                },
                ("session_id",),
            ),
            self._tool(
                "shell_stderr",
                "Read bounded stderr bytes from a cursor.",
                {
                    "session_id": identifier,
                    "cursor": cursor,
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": _MAX_READ_BYTES,
                    },
                },
                ("session_id",),
            ),
            self._tool(
                "shell_stdin",
                "Write bounded UTF-8 data to process stdin.",
                {"session_id": identifier, "data": {"type": "string"}},
                ("session_id", "data"),
            ),
            self._tool(
                "shell_close_stdin",
                "Close process stdin.",
                {"session_id": identifier},
                ("session_id",),
            ),
            self._tool(
                "shell_interrupt",
                "Request a graceful process-group interrupt.",
                {"session_id": identifier},
                ("session_id",),
            ),
            self._tool(
                "shell_terminate",
                "Terminate a process session after interrupt is insufficient.",
                {"session_id": identifier},
                ("session_id",),
            ),
            self._tool(
                "shell_kill",
                "Hard-kill a process session only as the final escalation.",
                {"session_id": identifier},
                ("session_id",),
            ),
            self._tool(
                "shell_recover",
                "Recover a previously dispatched process session without replaying it.",
                {
                    "session_id": {"type": "string"},
                    "work_id": {"type": "string"},
                    "action_sequence": {"type": "integer", "minimum": 0},
                },
            ),
        )

    def execute(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        args = dict(arguments)
        if name == "shell_start":
            if not self.workspace_runtime.allow_mutations:
                return {
                    "ok": False,
                    "error": "Shell execution requires explicit user authorization.",
                }
            try:
                command = self.workspace_runtime.prepare_development_command(
                    args.get("command")
                )
                cwd = self.workspace_runtime.prepare_process_cwd(args.get("cwd") or ".")
            except (OSError, UnicodeError, ValueError) as exc:
                return {
                    "ok": False,
                    "error": str(exc),
                    "error_code": type(exc).__name__,
                }
            action, _decision = self.workspace_runtime.gate.propose_action(
                "shell_session_start",
                command[0],
                {
                    "arguments": command[1:],
                    "cwd": str(cwd),
                    "command_digest": _digest(command),
                    "attempt": self.workspace_runtime.next_effect_attempt(),
                },
            )
            approval = self.workspace_runtime.gate.request_approval(
                action, approver="explicit_workspace_request"
            )

            def effect(_parameters: dict[str, Any]) -> dict[str, Any]:
                return self.store.start(
                    command,
                    cwd=cwd,
                    environment=self.workspace_runtime.safe_process_environment(),
                    work_id=str(args.get("_work_id") or ""),
                    tool_call_id=str(args.get("_tool_call_id") or ""),
                    action_sequence=int(args.get("_action_sequence") or 0),
                )

            receipt = self.workspace_runtime.gate.execute(action, approval, effect)
            result = dict(receipt.result or {})
            return {
                **result,
                "ok": receipt.success and bool(result.get("ok")),
                "receipt_id": receipt.receipt_id,
            }
        session_id = str(args.get("session_id") or "")
        handlers = {
            "shell_status": lambda: self.store.status(session_id),
            "shell_attach": lambda: self.store.attach(session_id),
            "shell_detach": lambda: self.store.detach(session_id),
            "shell_stdout": lambda: self.store.read_output(
                session_id,
                "stdout",
                cursor=args.get("cursor"),
                limit=int(args.get("limit") or _MAX_READ_BYTES),
            ),
            "shell_stderr": lambda: self.store.read_output(
                session_id,
                "stderr",
                cursor=args.get("cursor"),
                limit=int(args.get("limit") or _MAX_READ_BYTES),
            ),
            "shell_stdin": lambda: self.store.write_stdin(
                session_id, str(args.get("data") or "")
            ),
            "shell_close_stdin": lambda: self.store.close_stdin(session_id),
            "shell_interrupt": lambda: self.store.interrupt(session_id),
            "shell_terminate": lambda: self.store.terminate(session_id),
            "shell_kill": lambda: self.store.kill(session_id),
            "shell_recover": lambda: self.store.recover(
                session_id=session_id,
                work_id=str(args.get("work_id") or ""),
                action_sequence=int(args.get("action_sequence") or 0),
            ),
        }
        handler = handlers.get(name)
        if handler is None:
            return {"ok": False, "error": f"unknown process session tool: {name}"}
        try:
            return dict(handler())
        except (OSError, RuntimeError, ValueError) as exc:
            return {"ok": False, "error": str(exc), "error_code": type(exc).__name__}

    @staticmethod
    def _tool(
        name: str,
        description: str,
        properties: Mapping[str, Any],
        required: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": dict(properties),
                    "required": list(required),
                    "additionalProperties": False,
                },
            },
        }


__all__ = [
    "ProcessSession",
    "ProcessSessionState",
    "ProcessSessionStore",
    "ProcessSessionToolRuntime",
]

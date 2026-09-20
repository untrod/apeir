# -*- coding: utf-8 -*-
"""ProcessSupervisor — governs the lifecycle of an external agent subprocess."""

from __future__ import annotations

import json
import logging
import os
import shlex
import signal
import subprocess
import tempfile
import threading
import time

from nous_runtime.agents.adapters.artifact_collector import ArtifactCollector
from nous_runtime.agents.adapters.environment_filter import EnvironmentFilter
from nous_runtime.agents.adapters.event_parser import StructuredEventParser
from nous_runtime.agents.adapters.output_limiter import OutputLimiter
from nous_runtime.agents.adapters.workspace_guard import WorkspaceGuard
from nous_runtime.agents.external.models import (
    AgentDescriptor,
    AgentProcessState,
    AgentResourceUsage,
    AgentRunContext,
    AgentRunRequest,
    AgentRunResult,
)

_log = logging.getLogger("nous.agents.supervisor")


class ProcessSupervisor:
    """Supervises the execution of an external agent process.

    Responsibilities:
    - Validate the workspace before execution
    - Build a sanitized environment
    - Spawn the agent subprocess
    - Capture stdout/stderr separately with output limits
    - Enforce timeout
    - Support cancellation and graceful/forced termination
    - Collect artifacts and changed files
    - Record resource usage
    - Build structured AgentRunResult
    """

    def __init__(
        self,
        descriptor: AgentDescriptor,
        *,
        grace_period_seconds: float = 5.0,
    ):
        self._descriptor = descriptor
        self._grace_period = grace_period_seconds
        self._process: subprocess.Popen[bytes] | None = None
        self._state = AgentProcessState.CREATED
        self._cancel_event = threading.Event()
        self._start_time: float = 0.0
        self._end_time: float = 0.0

    @property
    def state(self) -> AgentProcessState:
        return self._state

    def run(self, request: AgentRunRequest, context: AgentRunContext) -> AgentRunResult:
        """Execute the agent with the given request and context.

        This is the main entry point. It handles the full lifecycle:
        validate → prepare → execute → collect → report.
        """
        run_id = request.run_id
        _log.info("Starting agent run %s with agent %s", run_id, request.agent_id)

        # Phase 1: Validate
        guard = WorkspaceGuard(context.workspace_path)
        for input_file in context.input_files:
            guard.validate_path(input_file)
        env_filter = EnvironmentFilter(
            allowlist=self._descriptor.environment_allowlist,
            blocklist=self._descriptor.environment_blocklist,
        )
        limiter = OutputLimiter(limit_bytes=self._descriptor.output_limit_bytes)
        parser = StructuredEventParser()
        collector = ArtifactCollector(context.workspace_path)

        before_snapshot = ArtifactCollector.snapshot_workspace(context.workspace_path)

        environment_values = dict(context.environment)
        environment_values.update({
            "NOUS_RUN_ID": run_id,
            "NOUS_TASK_ID": request.task_id,
            "NOUS_WORKSPACE": context.workspace_path,
        })
        env = env_filter.build_env(extra=environment_values)
        request_environment = {
            key: env[key]
            for key in context.environment
            if key in env
        }

        request_path = ""
        try:
            cmd = self._build_command(
                request,
                context,
                request_environment=request_environment,
            )
            request_path = cmd[-1]
        except ValueError as exc:
            return AgentRunResult(
                run_id=run_id,
                task_id=request.task_id,
                agent_id=request.agent_id,
                status="FAILED",
                exit_code=-1,
                errors=(str(exc),),
            )

        # Phase 4: Execute
        self._state = AgentProcessState.STARTING
        self._start_time = time.monotonic()

        try:
            exit_code, stdout_text, stderr_text, timed_out, resource_usage = (
                self._execute(
                    cmd=cmd,
                    env=env,
                    cwd=context.workspace_path,
                    timeout_ms=request.timeout_ms,
                    stdout_limiter=limiter,
                    parser=parser,
                )
            )
        except Exception as exc:
            _log.exception("Agent process failed: %s", exc)
            self._state = AgentProcessState.FAILED
            return AgentRunResult(
                run_id=run_id,
                task_id=request.task_id,
                agent_id=request.agent_id,
                status="FAILED",
                exit_code=-1,
                errors=(str(exc),),
                raw_output=limiter.getvalue_text(),
            )
        finally:
            if request_path:
                try:
                    os.unlink(request_path)
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    _log.warning("Failed to remove agent request file: %s", exc)

        self._end_time = time.monotonic()
        duration_ms = int((self._end_time - self._start_time) * 1000)

        # Phase 5: Determine status
        if self._cancel_event.is_set():
            status = "CANCELLED"
            self._state = AgentProcessState.CANCELLED
        elif timed_out:
            status = "TIMED_OUT"
            self._state = AgentProcessState.TIMED_OUT
        elif exit_code == 0:
            status = "COMPLETED"
            self._state = AgentProcessState.COMPLETED
        else:
            status = "FAILED"
            self._state = AgentProcessState.FAILED

        # Phase 6: Collect artifacts and changed files
        artifacts = collector.collect(run_id, request.expected_artifacts)
        changed = collector.discover_changed_files(before_snapshot)
        changed_files = tuple(changed.keys())

        # Phase 7: Parse structured events for test results
        tests_executed, tests_passed, tests_failed = self._extract_test_results(parser)

        # Phase 8: Build result
        warnings: list[str] = []
        if limiter.truncated:
            warnings.append(
                f"Output truncated at {limiter.limit} bytes "
                f"({limiter.bytes_written} bytes written)"
            )
        if timed_out:
            warnings.append(f"Run timed out after {request.timeout_ms}ms")

        return AgentRunResult(
            run_id=run_id,
            task_id=request.task_id,
            agent_id=request.agent_id,
            status=status,
            exit_code=exit_code,
            summary=self._build_summary(status, exit_code, duration_ms, changed_files),
            started_at="",
            duration_ms=duration_ms,
            changed_files=changed_files,
            commands_executed=1,
            tests_executed=tests_executed,
            tests_passed=tests_passed,
            tests_failed=tests_failed,
            artifacts=tuple(artifacts),
            warnings=tuple(warnings),
            errors=tuple(self._extract_errors(stderr_text, parser)),
            resource_usage=resource_usage,
            raw_output=stdout_text,
        )

    def cancel(self) -> None:
        """Request cancellation of the running process."""
        self._cancel_event.set()
        if self._process and self._process.poll() is None:
            _log.info("Sending SIGTERM to agent process (pid=%s)", self._process.pid)
            self._terminate_process_tree(force=False)

    def _build_command(
        self,
        request: AgentRunRequest,
        context: AgentRunContext,
        *,
        request_environment: dict[str, str],
    ) -> list[str]:
        """Build the command line for the agent process.

        Writes the request to a temporary JSON file and passes the file path
        as the only argument, so any executable can read the structured input.
        """
        exe = self._descriptor.executable_reference
        if not exe:
            raise ValueError("No executable reference in agent descriptor")

        # Preserve quoted executable paths while still passing an argument array.
        cmd = shlex.split(exe, posix=os.name != "nt")
        if not cmd:
            raise ValueError("No executable command in agent descriptor")

        request_data = request.to_dict()
        request_data["workspace_path"] = context.workspace_path
        request_data["environment"] = dict(request_environment)
        request_data["input_files"] = list(context.input_files)

        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            prefix=".nous_run_",
            dir=context.workspace_path,
            delete=False,
            encoding="utf-8",
        )
        try:
            json.dump(request_data, tmp)
        finally:
            tmp.close()
        try:
            os.chmod(tmp.name, 0o600)
        except OSError:
            pass

        cmd.append(tmp.name)
        return cmd

    def _execute(
        self,
        cmd: list[str],
        env: dict[str, str],
        cwd: str,
        timeout_ms: int,
        stdout_limiter: OutputLimiter,
        parser: StructuredEventParser,
    ) -> tuple[int, str, str, bool, AgentResourceUsage]:
        """Execute the subprocess with timeout and output capture."""
        self._state = AgentProcessState.RUNNING

        popen_options: dict[str, object] = {}
        if os.name == "nt":
            popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_options["start_new_session"] = True

        try:
            self._process = subprocess.Popen(
                cmd,
                env=env,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **popen_options,
            )
        except FileNotFoundError:
            return -1, "", f"Executable not found: {cmd[0]}", False, AgentResourceUsage()
        except PermissionError as exc:
            return -1, "", f"Permission denied: {exc}", False, AgentResourceUsage()

        timeout_seconds = timeout_ms / 1000.0
        timed_out = False

        try:
            stdout_bytes, stderr_bytes = self._process.communicate(
                timeout=timeout_seconds
            )
        except subprocess.TimeoutExpired:
            timed_out = True
            self._graceful_terminate()
            try:
                stdout_bytes, stderr_bytes = self._process.communicate(timeout=5.0)
            except subprocess.TimeoutExpired:
                self._terminate_process_tree(force=True)
                stdout_bytes, stderr_bytes = self._process.communicate(timeout=5.0)

        exit_code = self._process.returncode if self._process.returncode is not None else -1

        # Apply output limits
        stdout_limiter.write(stdout_bytes or b"")
        stdout_text = stdout_limiter.getvalue_text()

        stderr_text = ""
        if stderr_bytes:
            stderr_limit = OutputLimiter(limit_bytes=stdout_limiter.limit)
            stderr_limit.write(stderr_bytes)
            stderr_text = stderr_limit.getvalue_text()

        # Parse structured events from stdout
        parser.parse_stream(stdout_text)

        # Measure resource usage (platform-specific)
        resource_usage = self._measure_resources()

        return exit_code, stdout_text, stderr_text, timed_out, resource_usage

    def _graceful_terminate(self) -> None:
        if self._process is None or self._process.poll() is not None:
            return
        _log.info("Gracefully terminating agent process tree (pid=%s)", self._process.pid)
        self._terminate_process_tree(force=False)

    def _terminate_process_tree(self, *, force: bool) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return
        if os.name == "nt":
            if not force:
                try:
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                    return
                except (OSError, ValueError):
                    process.terminate()
                    return
            completed = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5.0,
            )
            if completed.returncode != 0 and process.poll() is None:
                process.kill()
            return
        try:
            process_group = os.getpgid(process.pid)
            os.killpg(process_group, signal.SIGKILL if force else signal.SIGTERM)
        except (OSError, ProcessLookupError):
            if process.poll() is None:
                process.kill() if force else process.terminate()

    def _measure_resources(self) -> AgentResourceUsage:
        """Measure resource usage of the completed process."""
        wall_time = int((self._end_time - self._start_time) * 1000) if self._end_time else 0
        return AgentResourceUsage(wall_time_ms=wall_time)

    @staticmethod
    def _extract_test_results(parser: StructuredEventParser) -> tuple[int, int, int]:
        """Extract test counts from structured events."""
        total = 0
        passed = 0
        failed = 0
        for event in parser.events:
            if event.get("type") in ("test.completed", "test_result"):
                total += 1
                if event.get("status") == "passed":
                    passed += 1
                else:
                    failed += 1
            if "tests_total" in event:
                total = max(total, int(event.get("tests_total", 0)))
            if "tests_passed" in event:
                passed = max(passed, int(event.get("tests_passed", 0)))
            if "tests_failed" in event:
                failed = max(failed, int(event.get("tests_failed", 0)))
        return total, passed, failed

    @staticmethod
    def _extract_errors(stderr_text: str, parser: StructuredEventParser) -> list[str]:
        """Extract error messages from stderr and structured events."""
        errors: list[str] = []
        for event in parser.events:
            if event.get("type") in ("error", "run.error"):
                msg = event.get("message") or event.get("error") or ""
                if msg:
                    errors.append(msg)
        if stderr_text.strip():
            # Take last 5 lines of stderr as potential errors
            stderr_lines = stderr_text.strip().splitlines()
            errors.extend(stderr_lines[-5:])
        return errors

    @staticmethod
    def _build_summary(
        status: str, exit_code: int, duration_ms: int, changed_files: tuple[str, ...]
    ) -> str:
        if status == "COMPLETED":
            return (
                f"Run completed in {duration_ms}ms. "
                f"{len(changed_files)} files changed."
            )
        elif status == "FAILED":
            return f"Run failed with exit code {exit_code}."
        elif status == "CANCELLED":
            return "Run was cancelled."
        elif status == "TIMED_OUT":
            return f"Run timed out after {duration_ms}ms."
        return f"Run ended with status {status}."

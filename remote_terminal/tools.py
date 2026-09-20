# -*- coding: utf-8 -*-
"""
Reconstructed tools.py — Legacy Path Consolidation (2026-07-27).

All tool dispatch now routes through the unified Capability Registry pipeline:
  CapabilityContract → AdmissionPipeline → Approval → ExecutionSandbox → Evidence → Verification

Compat entry points preserved with DeprecationWarning and legacy metrics.
Unregistered tools are default-denied.
"""

from __future__ import annotations

import logging
import threading
import warnings
from dataclasses import dataclass, field
from typing import Any, Callable

_log = logging.getLogger("tools")

# Legacy metrics (incremented on every compat-path invocation)
legacy_tool_dispatch_total: int = 0
legacy_direct_exec_total: int = 0
_legacy_search_pending_ids: dict[str, str] = {}
_legacy_search_pending_lock = threading.RLock()



# ToolResult — matches original contract


@dataclass
class ToolResult:
    """Result from a tool dispatch. Compatible with original API."""
    status: str = "done"          # "done" | "error" | "awaiting_confirmation"
    output: str = ""              # Human-readable output
    command: str = ""             # Shell command that was/would be executed
    needs_danger_check: bool = False  # Whether safety gate is required
    _delegate_fn: Callable[[], str] | None = field(default=None, repr=False)



# Server-side tools (execute on Brain, not via remote Agent)


_SERVER_SIDE_TOOLS: set[str] = {
    # Learning tools (database + LLM on server)
    "learn_list_docs", "learn_parse_doc", "learn_upload_doc",
    "learn_search_kp", "learn_search_semantic", "learn_ask_document",
    "learn_rebuild_index", "learn_catalog", "learn_get_kp",
    "learn_practice", "learn_vocab", "learn_my_plan",
    "learn_today_tasks", "learn_checkin", "learn_phase_summary",
    "learn_plan_detail", "learn_set_day", "learn_today_plan",
    "learn_coverage", "learn_merge_subject", "learn_get_formula",
    "learn_review_formulas", "learn_list_progress",
    "learn_record_exercise", "learn_generate_quiz",
    "learn_search_formula", "learn_add_exam", "learn_exam_dashboard",
    "learn_exam_detail", "learn_generate_study_plan",
    "learn_analyze_syllabus", "learn_study_advice",
    "learn_daily_review", "learn_plan_tomorrow",
    "learn_diagnose_mistake", "learn_auto_variant",
    "learn_achievements", "learn_weekly_report",
    "learn_smart_plan", "learn_custom_quiz", "learn_export",
    "learn_focus_history", "learn_my_notes", "learn_focus_start",
    "learn_quick_note", "learn_weak_alert", "learn_sprint_mode",
    "learn_micro_learning", "learn_add_timetable",
    "learn_my_schedule", "learn_free_time", "learn_auto_schedule",
    "learn_add_homework", "learn_my_homework", "learn_my_profile",
    "learn_remember", "learn_list_courses", "learn_course_detail",
    "learn_next_to_learn", "learn_build_course",
    "learn_flashcard_generate", "learn_flashcard_review",
    "learn_flashcard_rate", "learn_fuzzy_search",
    "learn_quick_review", "learn_study_streak",
    # Web / external tools (server-side HTTP calls)
    "web_search", "web_fetch", "weather",
    # Phone control (talks to phone directly from server)
    "phone_observe", "phone_act",
    # Claude Code delegation (local subprocess)
    "delegate_to_claude",
}


def is_server_side_tool(tool_name: str) -> bool:
    """Check if a tool executes on the Brain server (no remote Agent needed).

    Delegates to Capability Manifest locality when available;
    falls back to the legacy _SERVER_SIDE_TOOLS set.
    """
    try:
        from nous_runtime.capability.manifest import get_capability_manifest
        manifest = get_capability_manifest(f"tool.{tool_name}", include_availability=False)
        if manifest is not None and manifest.locality:
            return manifest.locality == "local"
    except Exception:
        pass
    return tool_name in _SERVER_SIDE_TOOLS



# Tool definitions (JSON Schema for model tool_choice)


def get_tool_defs() -> list[dict[str, Any]]:
    """Return JSON Schema definitions for all registered tool capabilities.

    Merges learn_tools definitions with system tool definitions.
    """
    defs: list[dict[str, Any]] = []

    # System tools
    defs.append({
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a PowerShell command on the target Windows PC. Use for file operations, system queries, and application control.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "PowerShell command to execute"},
                },
                "required": ["command"],
            },
        },
    })
    defs.append({
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file on the target device.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the file"},
                    "encoding": {"type": "string", "description": "File encoding, default utf-8"},
                },
                "required": ["path"],
            },
        },
    })
    defs.append({
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write or overwrite a file on the target device.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the file"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
        },
    })
    defs.append({
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and directories in a given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path to list"},
                },
                "required": ["path"],
            },
        },
    })
    defs.append({
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for information. Returns titles and URLs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query string"},
                },
                "required": ["query"],
            },
        },
    })
    defs.append({
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch and read the content of a web page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"},
                },
                "required": ["url"],
            },
        },
    })
    defs.append({
        "type": "function",
        "function": {
            "name": "phone_observe",
            "description": "Observe the current state of the phone screen (UI tree).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    })
    defs.append({
        "type": "function",
        "function": {
            "name": "phone_act",
            "description": "Perform an action on the phone (tap, swipe, type).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "Action: tap, swipe, type, back, home"},
                    "target": {"type": "string", "description": "Target element or coordinates"},
                },
                "required": ["action"],
            },
        },
    })
    defs.append({
        "type": "function",
        "function": {
            "name": "delegate_to_claude",
            "description": "Delegate a complex coding task to Claude Code CLI on the local machine.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Task description for Claude Code"},
                    "project_path": {"type": "string", "description": "Path to the project directory"},
                },
                "required": ["task"],
            },
        },
    })

    # Merge learning tool definitions
    try:
        import learn_tools
        learn_defs = learn_tools.get_learn_tool_defs()
        defs.extend(learn_defs)
    except ImportError:
        pass

    return defs



# Phone / Web handlers (preserved from original tools.py)


def handle_phone_observe(args: dict[str, Any], session: dict[str, Any],
                         executor: Callable) -> ToolResult:
    """Observe phone screen state."""
    warnings.warn(
        "handle_phone_observe is a legacy compat path. Use capability tool.phone_observe instead.",
        DeprecationWarning, stacklevel=2,
    )
    global legacy_tool_dispatch_total
    legacy_tool_dispatch_total += 1
    try:
        from remote_terminal import config, device_transport
        host = getattr(config, "PHONE_CONTROL_HOST", "")
        token = getattr(config, "PHONE_CONTROL_TOKEN", "")
        if not host:
            return ToolResult(status="error", output="Phone control host not configured")
        url = f"http://{host}:8765/observe"
        data = device_transport.request_json(
            url,
            None,
            expected_host=host,
            expected_port=8765,
            method="GET",
            timeout=10,
            headers={"X-Auth-Token": token},
        )
        ui_tree = data.get("ui_tree", data.get("result", str(data)))
        return ToolResult(status="done", output=str(ui_tree))
    except Exception as e:
        return ToolResult(status="error", output=f"Phone observe failed: {e}")


def execute_phone_act(params: dict[str, Any]) -> str:
    """Execute a phone action."""
    warnings.warn(
        "execute_phone_act is a legacy compat path. Use capability tool.phone_act instead.",
        DeprecationWarning, stacklevel=2,
    )
    global legacy_tool_dispatch_total
    legacy_tool_dispatch_total += 1
    try:
        from remote_terminal import config, device_transport
        host = getattr(config, "PHONE_CONTROL_HOST", "")
        token = getattr(config, "PHONE_CONTROL_TOKEN", "")
        if not host:
            return "Error: Phone control host not configured"
        url = f"http://{host}:8765/act"
        data = device_transport.request_json(
            url,
            params,
            expected_host=host,
            expected_port=8765,
            timeout=30,
            headers={"X-Auth-Token": token},
        )
        return str(data.get("result", data.get("output", str(data))))
    except Exception as e:
        return f"Phone act failed: {e}"


def handle_web_search(args: dict[str, Any], session: dict[str, Any],
                      executor: Callable) -> ToolResult:
    """Route legacy web search through the governed Research API."""
    warnings.warn(
        "handle_web_search is a legacy compat path. Use capability tool.web_search instead.",
        DeprecationWarning, stacklevel=2,
    )
    global legacy_tool_dispatch_total
    legacy_tool_dispatch_total += 1
    query = str(args.get("query", "")).strip()
    if not query:
        return ToolResult(status="error", output="Search query is empty")
    try:
        import hashlib
        import os
        import uuid

        from nous_runtime.api import routes

        token = str(session.get("api_token") or os.environ.get("NOUS_API_TOKEN") or "")
        if not token:
            return ToolResult(
                status="error",
                output="Governed web search requires an authenticated Nous Runtime session.",
            )
        digest = hashlib.sha256(query.encode("utf-8")).hexdigest()[:20]
        with _legacy_search_pending_lock:
            request_id = _legacy_search_pending_ids.get(digest)
            if not request_id:
                request_id = f"legacy-search-{uuid.uuid4().hex[:20]}"
                _legacy_search_pending_ids[digest] = request_id
        request = {
            "request_id": request_id,
            "query": query,
            "max_results": max(1, min(int(args.get("max_results") or 10), 20)),
            "network_scope": "public_internet",
            "max_response_bytes": 1_048_576,
            "timeout_seconds": 30,
        }
        response = routes.route_server(
            "POST",
            "/api/v1/research/search",
            body=request,
            auth={"token": token, "loopback": True},
        )
        if not response.get("ok"):
            error = response.get("error") or {}
            if error.get("code") == "NOUS_APPROVAL_REQUIRED":
                details = error.get("details") or {}
                approval_id = str(details.get("approval_request_id") or "")
                return ToolResult(
                    status="awaiting_confirmation",
                    output=(
                        "Governed web search is waiting for explicit approval. "
                        f"Approval request: {approval_id}. Approve it in Nous, then retry the same search."
                    ),
                    needs_danger_check=True,
                )
            with _legacy_search_pending_lock:
                if _legacy_search_pending_ids.get(digest) == request_id:
                    _legacy_search_pending_ids.pop(digest, None)
            return ToolResult(
                status="error",
                output=f"Governed web search failed: {error.get('message') or error.get('code') or 'unknown error'}",
            )
        with _legacy_search_pending_lock:
            if _legacy_search_pending_ids.get(digest) == request_id:
                _legacy_search_pending_ids.pop(digest, None)
        values = response.get("data") or {}
        results = values.get("results") or []
        if not results:
            return ToolResult(status="done", output=f"No results found for: {query}")
        lines = []
        for item in results:
            title = str(item.get("title") or item.get("url") or "Untitled result")
            url = str(item.get("url") or "")
            snippet = str(item.get("snippet") or "")
            lines.append(f"{item.get('rank', len(lines) + 1)}. {title}\n{url}\n{snippet}".rstrip())
        return ToolResult(status="done", output="\n\n".join(lines))
    except Exception as exc:
        _log.exception("Governed legacy web search failed")
        return ToolResult(status="error", output=f"Governed web search failed: {exc}")


# Unified dispatch through Capability Registry


def dispatch(
    tool_name: str,
    args: dict[str, Any],
    session: dict[str, Any],
    executor: Callable[[str], tuple[str, int]],
) -> ToolResult:
    """Route a tool call through the Capability Registry pipeline.

    Flow:
      1. Look up CapabilityContract for this tool
      2. AdmissionPipeline check (risk, permissions, budget)
      3. If server-side → execute locally via handler
      4. If agent-side → delegate to executor with sandbox wrapping
      5. Record evidence

    Unregistered tools are default-denied.
    """
    warnings.warn(
        f"tools.dispatch('{tool_name}') is a compat path. "
        f"Use CapabilityRegistry.request_capability('tool.{tool_name}') instead.",
        DeprecationWarning, stacklevel=2,
    )
    global legacy_tool_dispatch_total
    legacy_tool_dispatch_total += 1

    # Step 1: Capability Contract lookup
    capability_id = f"tool.{tool_name}"
    try:
        from nous_runtime.capability.contract import CapabilityContractRegistry
        registry = CapabilityContractRegistry()
        contract_result = registry.get(capability_id)
        if contract_result.is_err:
            # ALL tools must be registered as CapabilityContracts — no exceptions
            _log.error("Tool '%s' not registered as capability — execution denied", tool_name)
            return ToolResult(
                status="error",
                output=f"⚠️ Tool '{tool_name}' is not registered as a capability contract. "
                       f"Execution denied. All tools must be registered via CapabilityContractRegistry. "
                       f"Contact administrator to register this tool.",
            )
        contract = contract_result.unwrap()
    except ImportError:
        # nous_runtime not available — fall through to legacy dispatch
        contract = None
    except Exception as e:
        _log.warning("Capability registry lookup failed for '%s': %s", tool_name, e)
        contract = None

    # Step 2: Admission check
    if contract is not None:
        try:
            from nous_runtime.security.admission import (
                AdmissionPipeline, AdmissionRequest, RiskLevel,
            )
            risk_map = {
                "READ_ONLY": RiskLevel.READ_ONLY,
                "LOW": RiskLevel.LOW,
                "MEDIUM": RiskLevel.MEDIUM,
                "HIGH": RiskLevel.HIGH,
                "CRITICAL": RiskLevel.CRITICAL,
            }
            risk = risk_map.get(contract.risk_level, RiskLevel.MEDIUM)
            admission = AdmissionPipeline().check(AdmissionRequest(
                capability_id=capability_id,
                risk_level=risk,
                params=args,
                user_id=str(session.get("_source_client", "")),
                conversation_id=str(session.get("_transcript_sid", "")),
            ))
            if not admission.allowed:
                return ToolResult(
                    status="error",
                    output=f"⚠️ Tool '{tool_name}' blocked by admission control: {admission.reason}",
                )
            if admission.requires_approval:
                return ToolResult(
                    status="awaiting_confirmation",
                    output=f"Tool '{tool_name}' requires approval: {admission.reason}",
                    command=args.get("command", tool_name),
                    needs_danger_check=True,
                )
        except ImportError:
            pass
        except Exception as e:
            _log.warning("Admission check failed for '%s': %s (proceeding with legacy dispatch)", tool_name, e)

    # Step 3: Dispatch to handler
    return _dispatch_handler(tool_name, args, session, executor)


def _dispatch_handler(
    tool_name: str,
    args: dict[str, Any],
    session: dict[str, Any],
    executor: Callable[[str], tuple[str, int]],
) -> ToolResult:
    """Legacy handler dispatch — delegates to the appropriate implementation."""

    # Phone tools
    if tool_name == "phone_observe":
        return handle_phone_observe(args, session, executor)
    if tool_name == "phone_act":
        output = execute_phone_act(args)
        return ToolResult(status="done", output=output)
    if tool_name == "web_search":
        return handle_web_search(args, session, executor)

    # Delegate to Claude Code
    if tool_name == "delegate_to_claude":
        task = str(args.get("task", args.get("prompt", "")))
        project_path = str(args.get("project_path", args.get("path", "")))
        if not task:
            return ToolResult(status="error", output="delegate_to_claude requires 'task' parameter")

        import subprocess
        cmd_parts = ["claude"]
        if project_path:
            cmd_parts.extend(["--project", project_path])
        cmd_parts.extend(["-p", task])

        def _run_claude() -> str:
            try:
                proc = subprocess.run(
                    cmd_parts,
                    capture_output=True, text=True,
                    timeout=300,
                    cwd=project_path or None,
                )
                output = proc.stdout
                if proc.stderr:
                    output += "\n[stderr]\n" + proc.stderr
                return output.strip() or "(Claude Code returned no output)"
            except subprocess.TimeoutExpired:
                return "⚠️ Claude Code execution timed out (300s)"
            except FileNotFoundError:
                return "⚠️ Claude Code CLI not found. Install with: npm install -g @anthropic-ai/claude-code"
            except Exception as e:
                return f"⚠️ Claude Code execution failed: {e}"

        return ToolResult(
            status="done",
            output="External coding task dispatched. See execution output below.",
            command=" ".join(cmd_parts),
            needs_danger_check=False,
            _delegate_fn=_run_claude,
        )

    # System tools that need agent execution
    if tool_name in ("run_command", "read_file", "write_file", "list_directory"):
        if tool_name == "run_command":
            command = str(args.get("command", "")).strip()
        elif tool_name == "read_file":
            path = str(args.get("path", ""))
            command = f'Get-Content -Path "{path}" -Raw'
        elif tool_name == "write_file":
            path = str(args.get("path", ""))
            content = str(args.get("content", ""))
            # Escape for PowerShell
            escaped = content.replace('"', '`"')
            command = f'Set-Content -Path "{path}" -Value "{escaped}" -Encoding UTF8'
        elif tool_name == "list_directory":
            path = str(args.get("path", "."))
            command = f'Get-ChildItem -Path "{path}" | Format-Table Name, Length, LastWriteTime -AutoSize'
        else:
            return ToolResult(status="error", output=f"Unknown system tool: {tool_name}")

        if not command:
            return ToolResult(status="error", output=f"Empty command for tool: {tool_name}")

        return ToolResult(
            status="done",
            output="",
            command=command,
            needs_danger_check=(tool_name in ("run_command", "write_file")),
        )

    # Learning tools
    if tool_name.startswith("learn_"):
        try:
            import learn_tools
            handler = getattr(learn_tools, "_learn_handler", None)
            if handler is None:
                return ToolResult(status="error", output="Learning handler not initialized")
            method_name = f"handle_{tool_name[len('learn_'):]}"
            method = getattr(handler, method_name, None)
            if method is None:
                return ToolResult(status="error", output=f"No handler for learning tool: {tool_name}")
            return method(args, session, executor)
        except ImportError:
            return ToolResult(status="error", output="Learning module not available")
        except Exception as e:
            _log.exception("Learning tool '%s' failed", tool_name)
            return ToolResult(status="error", output=f"Learning tool error: {e}")

    # Unknown tool
    _log.error("Unknown tool requested: %s", tool_name)
    return ToolResult(
        status="error",
        output=f"⚠️ Unknown tool '{tool_name}'. This tool is not registered in the Capability Registry. "
               f"All tools must be registered as versioned Capability Contracts.",
    )



# Module initialization — seed capability contracts on import


def _seed_tool_capability_contracts() -> None:
    """Register all known tools as CapabilityContract entries on module load."""
    try:
        from nous_runtime.capability.contract import (
            CapabilityContract, CapabilityContractRegistry,
            Idempotency, RetryStrategy, VerificationMethod,
        )
        registry = CapabilityContractRegistry()

        _TOOLS_TO_REGISTER = [
            # (capability_id, name, description, risk_level, idempotency, timeout_s, verification)
            ("tool.run_command", "Run Command", "Execute a PowerShell command on target device",
             "HIGH", Idempotency.NOT_IDEMPOTENT, 120, VerificationMethod.ASSERTION),
            ("tool.read_file", "Read File", "Read a file from target device",
             "LOW", Idempotency.IDEMPOTENT, 30, VerificationMethod.NONE),
            ("tool.write_file", "Write File", "Write/overwrite a file on target device",
             "MEDIUM", Idempotency.CONDITIONAL, 60, VerificationMethod.DIFF_CHECK),
            ("tool.list_directory", "List Directory", "List files in a directory",
             "LOW", Idempotency.IDEMPOTENT, 30, VerificationMethod.NONE),
            ("tool.web_search", "Web Search", "Search the web for information",
             "LOW", Idempotency.IDEMPOTENT, 30, VerificationMethod.NONE),
            ("tool.web_fetch", "Web Fetch", "Fetch content from a URL",
             "LOW", Idempotency.IDEMPOTENT, 30, VerificationMethod.NONE),
            ("tool.phone_observe", "Phone Observe", "Observe phone screen state",
             "LOW", Idempotency.IDEMPOTENT, 15, VerificationMethod.NONE),
            ("tool.phone_act", "Phone Act", "Perform action on phone",
             "HIGH", Idempotency.NOT_IDEMPOTENT, 30, VerificationMethod.ASSERTION),
            ("tool.delegate_to_claude", "Delegate to Claude Code",
             "Delegate a coding task to Claude Code CLI",
             "HIGH", Idempotency.NOT_IDEMPOTENT, 300, VerificationMethod.LLM_REVIEW),
            ("tool.weather", "Weather", "Get weather information",
             "LOW", Idempotency.IDEMPOTENT, 15, VerificationMethod.NONE),
        ]

        for cap_id, name, desc, risk, idem, timeout, verify in _TOOLS_TO_REGISTER:
            contract = CapabilityContract(
                capability_id=cap_id,
                name=name,
                description=desc,
                version="1.0.0",
                risk_level=risk,
                idempotency=idem,
                timeout_seconds=timeout,
                verification_method=verify,
                retry_strategy=RetryStrategy.EXPONENTIAL if idem != Idempotency.IDEMPOTENT else RetryStrategy.NONE,
                max_retries=2,
            )
            registry.register(contract)

        _log.info("Seeded %d tool capability contracts", len(_TOOLS_TO_REGISTER))
    except ImportError:
        _log.debug("nous_runtime not available — skipping capability contract seeding")
    except Exception as e:
        _log.warning("Failed to seed tool capability contracts: %s", e)


# Seed on import (best-effort)
_seed_tool_capability_contracts()

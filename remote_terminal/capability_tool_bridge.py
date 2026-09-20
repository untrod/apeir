# -*- coding: utf-8 -*-
"""
Capability Tool Bridge — Register all ~50 legacy tools as versioned Capability Contracts.

This module maps every tool (system + learning) to a formal CapabilityContract.
On import, it registers all contracts with the CapabilityContractRegistry.
Unregistered tools are default-denied by the new dispatch path.

Design:
  - One contract per tool
  - Each contract declares version, risk, idempotency, timeout, verification method
  - Learning tools get their schemas from learn_tools.LEARN_TOOL_DEFS
  - System tools get inline schemas
  - The bridge is idempotent — repeated imports won't duplicate registrations
"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger("capability_tool_bridge")

# Registry singleton (lazy init)
_registry = None
_contracts_registered = False


def _get_registry():
    """Lazy-init the CapabilityContractRegistry."""
    global _registry
    if _registry is None:
        try:
            from nous_runtime.capability.contract import CapabilityContractRegistry
            _registry = CapabilityContractRegistry()
        except ImportError:
            _registry = None
    return _registry


def register_all_tools() -> int:
    """Register all known tools as CapabilityContracts. Returns count registered."""
    global _contracts_registered
    if _contracts_registered:
        return 0

    registry = _get_registry()
    if registry is None:
        _log.debug("CapabilityContractRegistry not available — skipping tool registration")
        return 0

    try:
        from nous_runtime.capability.contract import (
            CapabilityContract, Idempotency, RetryStrategy, VerificationMethod,
        )
    except ImportError:
        _log.debug("nous_runtime.capability.contract not available")
        return 0

    count = 0

    # System tools
    system_tools = [
        {
            "capability_id": "tool.run_command",
            "name": "Run Command",
            "description": "Execute a PowerShell command on the target Windows PC. "
                           "Use for file operations, system queries, and application control.",
            "version": "1.0.0",
            "risk_level": "HIGH",
            "required_permissions": ["shell.execute"],
            "idempotency": Idempotency.NOT_IDEMPOTENT,
            "timeout_seconds": 120,
            "verification_method": VerificationMethod.ASSERTION,
            "retry_strategy": RetryStrategy.NONE,
            "max_retries": 0,
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "PowerShell command to execute"},
                },
                "required": ["command"],
            },
        },
        {
            "capability_id": "tool.read_file",
            "name": "Read File",
            "description": "Read the contents of a file on the target device.",
            "version": "1.0.0",
            "risk_level": "LOW",
            "idempotency": Idempotency.IDEMPOTENT,
            "timeout_seconds": 30,
            "verification_method": VerificationMethod.NONE,
            "retry_strategy": RetryStrategy.NONE,
            "max_retries": 0,
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the file"},
                },
                "required": ["path"],
            },
        },
        {
            "capability_id": "tool.write_file",
            "name": "Write File",
            "description": "Write or overwrite a file on the target device.",
            "version": "1.0.0",
            "risk_level": "MEDIUM",
            "required_permissions": ["file.write"],
            "idempotency": Idempotency.CONDITIONAL,
            "timeout_seconds": 60,
            "verification_method": VerificationMethod.DIFF_CHECK,
            "rollback_capability_id": "tool.restore_file",
            "retry_strategy": RetryStrategy.NONE,
            "max_retries": 0,
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the file"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
        },
        {
            "capability_id": "tool.list_directory",
            "name": "List Directory",
            "description": "List files and directories at a given path.",
            "version": "1.0.0",
            "risk_level": "LOW",
            "idempotency": Idempotency.IDEMPOTENT,
            "timeout_seconds": 30,
            "verification_method": VerificationMethod.NONE,
            "retry_strategy": RetryStrategy.NONE,
            "max_retries": 0,
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path to list"},
                },
                "required": ["path"],
            },
        },
        {
            "capability_id": "tool.web_search",
            "name": "Web Search",
            "description": "Search the web and return results.",
            "version": "1.0.0",
            "risk_level": "LOW",
            "idempotency": Idempotency.IDEMPOTENT,
            "timeout_seconds": 30,
            "verification_method": VerificationMethod.NONE,
            "retry_strategy": RetryStrategy.EXPONENTIAL,
            "max_retries": 2,
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        },
        {
            "capability_id": "tool.web_fetch",
            "name": "Web Fetch",
            "description": "Fetch and read content from a URL.",
            "version": "1.0.0",
            "risk_level": "LOW",
            "idempotency": Idempotency.IDEMPOTENT,
            "timeout_seconds": 30,
            "verification_method": VerificationMethod.NONE,
            "retry_strategy": RetryStrategy.EXPONENTIAL,
            "max_retries": 2,
            "input_schema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "format": "uri", "description": "URL to fetch"},
                },
                "required": ["url"],
            },
        },
        {
            "capability_id": "tool.phone_observe",
            "name": "Phone Observe",
            "description": "Capture the current UI state of the phone screen.",
            "version": "1.0.0",
            "risk_level": "LOW",
            "idempotency": Idempotency.IDEMPOTENT,
            "timeout_seconds": 15,
            "verification_method": VerificationMethod.NONE,
            "retry_strategy": RetryStrategy.EXPONENTIAL,
            "max_retries": 2,
        },
        {
            "capability_id": "tool.phone_act",
            "name": "Phone Act",
            "description": "Perform an action on the phone (tap, swipe, type, back, home).",
            "version": "1.0.0",
            "risk_level": "HIGH",
            "required_permissions": ["phone.control"],
            "idempotency": Idempotency.NOT_IDEMPOTENT,
            "timeout_seconds": 30,
            "verification_method": VerificationMethod.ASSERTION,
            "retry_strategy": RetryStrategy.NONE,
            "max_retries": 0,
            "input_schema": {
                "type": "object",
                "properties": {
                    "action": {"type": "string",
                               "enum": ["tap", "swipe", "type", "back", "home", "long_press"]},
                    "target": {"type": "string", "description": "Element ID, text, or coordinates"},
                },
                "required": ["action"],
            },
        },
        {
            "capability_id": "tool.delegate_to_claude",
            "name": "Delegate to Claude Code",
            "description": "Delegate a complex coding task to Claude Code CLI.",
            "version": "1.0.0",
            "risk_level": "HIGH",
            "required_permissions": ["claude.delegate"],
            "idempotency": Idempotency.NOT_IDEMPOTENT,
            "timeout_seconds": 300,
            "max_output_bytes": 5_000_000,
            "verification_method": VerificationMethod.LLM_REVIEW,
            "retry_strategy": RetryStrategy.NONE,
            "max_retries": 0,
            "input_schema": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Coding task description"},
                    "project_path": {"type": "string", "description": "Project directory path"},
                },
                "required": ["task"],
            },
        },
        {
            "capability_id": "tool.weather",
            "name": "Weather",
            "description": "Get current weather for a location.",
            "version": "1.0.0",
            "risk_level": "LOW",
            "idempotency": Idempotency.IDEMPOTENT,
            "timeout_seconds": 15,
            "verification_method": VerificationMethod.NONE,
            "retry_strategy": RetryStrategy.EXPONENTIAL,
            "max_retries": 2,
            "input_schema": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"},
                },
                "required": ["city"],
            },
        },
    ]

    for tool in system_tools:
        contract = CapabilityContract(
            capability_id=tool["capability_id"],
            name=tool["name"],
            description=tool["description"],
            version=tool.get("version", "1.0.0"),
            risk_level=tool["risk_level"],
            required_permissions=tool.get("required_permissions", []),
            idempotency=tool.get("idempotency", Idempotency.CONDITIONAL),
            timeout_seconds=tool.get("timeout_seconds", 30),
            max_output_bytes=tool.get("max_output_bytes", 1_000_000),
            verification_method=tool.get("verification_method", VerificationMethod.NONE),
            rollback_capability_id=tool.get("rollback_capability_id", ""),
            retry_strategy=tool.get("retry_strategy", RetryStrategy.EXPONENTIAL),
            max_retries=tool.get("max_retries", 2),
            input_schema=tool.get("input_schema", {}),
        )
        registry.register(contract)
        count += 1

    # Learning tools (from learn_tools.LEARN_TOOL_DEFS)
    try:
        import learn_tools
        learn_defs = learn_tools.get_learn_tool_defs()
        for tool_def in learn_defs:
            func = tool_def.get("function", {})
            tool_name = func.get("name", "")
            if not tool_name:
                continue
            capability_id = f"tool.{tool_name}"
            desc = func.get("description", "")

            # Determine risk based on tool type
            risk = "LOW"
            if any(kw in tool_name for kw in ("upload", "parse", "write", "delete", "clear",
                                                "merge", "export", "build", "generate")):
                risk = "MEDIUM"
            if any(kw in tool_name for kw in ("delete", "clear", "reset")):
                risk = "HIGH"

            # Determine idempotency
            if any(kw in tool_name for kw in ("search", "list", "get", "catalog",
                                                "dashboard", "coverage", "status", "progress",
                                                "achievements", "report", "detail", "review",
                                                "schedule", "profile", "streak", "history",
                                                "free_time", "fuzzy")):
                idem = Idempotency.IDEMPOTENT
            elif any(kw in tool_name for kw in ("delete", "clear", "reset", "merge")):
                idem = Idempotency.NOT_IDEMPOTENT
            else:
                idem = Idempotency.CONDITIONAL

            # Determine timeout
            if any(kw in tool_name for kw in ("parse", "generate", "build", "analyze")):
                timeout = 300
            elif any(kw in tool_name for kw in ("upload", "export", "rebuild")):
                timeout = 120
            else:
                timeout = 30

            contract = CapabilityContract(
                capability_id=capability_id,
                name=func.get("name", tool_name).replace("_", " ").title(),
                description=desc,
                version="1.0.0",
                risk_level=risk,
                idempotency=idem,
                timeout_seconds=timeout,
                verification_method=(
                    VerificationMethod.ASSERTION
                    if any(kw in tool_name for kw in ("generate", "create", "build"))
                    else VerificationMethod.NONE
                ),
                retry_strategy=(
                    RetryStrategy.EXPONENTIAL
                    if any(kw in tool_name for kw in ("generate", "parse", "search"))
                    else RetryStrategy.NONE
                ),
                max_retries=2 if any(kw in tool_name for kw in ("generate", "parse")) else 0,
                input_schema=func.get("parameters", {}),
            )
            registry.register(contract)
            count += 1
    except ImportError:
        _log.debug("learn_tools not available — skipping learning tool registration")
    except Exception as e:
        _log.warning("Failed to register learning tools: %s", e)

    _contracts_registered = True
    _log.info("Registered %d tools as CapabilityContracts", count)
    return count


def get_registered_tool_count() -> int:
    """Return the number of registered tool capability contracts."""
    registry = _get_registry()
    if registry is None:
        return 0
    return len(registry.list_all())


def is_tool_registered(tool_name: str) -> bool:
    """Check if a tool has a registered CapabilityContract."""
    registry = _get_registry()
    if registry is None:
        return False
    result = registry.get(f"tool.{tool_name}")
    return result.is_ok


def get_unregistered_tools(tool_names: list[str]) -> list[str]:
    """Return the list of tool names that lack a CapabilityContract."""
    return [name for name in tool_names if not is_tool_registered(name)]


# Auto-register on import
register_all_tools()

# -*- coding: utf-8 -*-
"""
Capability Resolver -enforces Capability->Provider->Execution separation.

The resolver ensures that:
  1. Capabilities declare WHAT (not WHO)
  2. Providers declare WHO/HOW (not WHAT)
  3. Execution always goes: request ->resolve ->select ->execute ->audit
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from nous_runtime.planner.observation import Observation

log = logging.getLogger("nous.capability.resolver")


@dataclass
class ResolutionResult:
    """Result of resolving a capability request to a provider."""
    capability_id: str
    provider_id: str = ""
    provider_name: str = ""
    resolved: bool = False
    error: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionResult:
    """Result of executing a capability via a provider."""
    ok: bool
    capability_id: str
    provider_id: str
    result: Any = None
    error: str = ""
    error_code: str = ""
    duration_ms: float = 0.0

    @classmethod
    def from_observation(cls, observation: Observation) -> "ExecutionResult":
        """Build the legacy execution result from an Observation.

        This keeps existing SDK/CLI callers stable while making
        Observation the canonical execution output inside the Runtime.
        """
        data = observation.data or {}
        metadata = observation.metadata or {}
        ok = observation.status == "success"
        return cls(
            ok=ok,
            capability_id=observation.capability or observation.tool,
            provider_id=str(metadata.get("provider_id", "")),
            result=data.get("result", data),
            error="; ".join(observation.errors) if observation.errors else "",
            error_code=str(metadata.get("error_code", "")),
            duration_ms=observation.duration_ms,
        )


def resolve_capability(capability_id: str) -> ResolutionResult:
    """
    Resolve a capability to an available provider.

    Steps:
      1. Look up capability in registry
      2. Find providers that serve this capability
      2b. Filter providers by platform compatibility (multi-arch)
      3. Select best provider (health, latency, cost)
      4. Return resolution

    Args:
        capability_id: Dotted capability name (e.g., "model.reason").

    Returns:
        ResolutionResult with selected provider or error.
    """
    result = ResolutionResult(capability_id=capability_id)

    # 1. Check capability exists
    try:
        from nous_runtime.compat.capability import get_capability, list_capabilities
        cap = get_capability(capability_id)
        if not cap:
            all_caps = list_capabilities()
            names = [c.get("name", "?") if isinstance(c, dict) else str(c) for c in all_caps[:10]]
            result.error = (
                f"Capability '{capability_id}' not found. "
                f"Available: {', '.join(names)}..."
            )
            return result
    except Exception as e:
        result.error = f"Capability lookup failed: {e}"
        return result

    # 2. Find providers
    try:
        from nous_runtime.compat.provider import list_providers, get_provider
        providers = list_providers()
        candidates = []
        for entry in providers:
            pid = entry.get("provider_id", entry.get("name", ""))
            caps = entry.get("capabilities", [])
            if capability_id in caps or any(
                capability_id.startswith(c.replace("*", "")) for c in caps
            ):
                candidates.append((pid, get_provider(pid)))

        if not candidates:
            result.error = f"No provider found for capability '{capability_id}'"
            return result

        # 2b. Platform-aware filtering (§multi-arch)
        try:
            from nous_runtime.platform import platform_service
            if not platform_service.can_execute(capability_id):
                result.error = (
                    f"Capability '{capability_id}' is restricted on this platform "
                    f"({platform_service.architecture.value}/{platform_service.tier.value}). "
                    f"Use a Tier 1 node (amd64/arm64) for full capabilities."
                )
                return result
        except ImportError:
            pass  # Platform service not available — skip filter

        # 3. Select best provider (prefer healthy, then first match)
        for pid, p in candidates:
            if p is None:
                continue
            try:
                h = p.health()
                if h.get("status") == "ok":
                    result.provider_id = pid
                    result.provider_name = getattr(p, "provider_name", pid)
                    result.resolved = True
                    return result
            except Exception:
                continue

        # Fallback: use first candidate even if health unknown
        if candidates:
            pid, p = candidates[0]
            if p is not None:
                result.provider_id = pid
                result.provider_name = getattr(p, "provider_name", pid)
                result.resolved = True
            else:
                result.error = (
                    f"No healthy provider for '{capability_id}'. "
                    f"Run: nous provider add"
                )
        else:
            result.error = (
                f"No provider configured for '{capability_id}'. "
                f"Run: nous provider add"
            )

    except Exception as e:
        result.error = f"Provider selection failed: {e}"

    return result


def execute_capability_observation(
    capability_id: str,
    *,
    _authorization_context=None,
    _governance_surface: str = "local_cli",
    _workspace_root: str = "",
    **params,
) -> Observation:
    """
    Execute a capability through the resolver pipeline and return Observation.

    Args:
        capability_id: Dotted capability name.
        **params: Parameters for the capability.

    Returns:
        Observation with structured data, errors, duration, and provider metadata.
    """
    import time
    start = time.time()

    # v0.2.0: executor-type dispatch — non-provider executors do not need
    # a provider adapter, so read the registered type before resolution.
    # This is the single capability-level entry point; the reliability
    # executor stays provider-only by definition (no double dispatch).
    cap_meta = _get_capability_metadata(capability_id)
    executor_type = str(cap_meta.get("executor_type") or "") or "provider"

    # 1. Resolve (provider executors only)
    resolution = ResolutionResult(capability_id=capability_id)
    if executor_type == "provider":
        resolution = resolve_capability(capability_id)
        if not resolution.resolved:
            return Observation.failure(
                "capability.execute",
                [resolution.error],
                capability=capability_id,
                duration_ms=(time.time() - start) * 1000,
                metadata={
                    "provider_id": "",
                    "provider_name": "",
                    "error_code": "NOUS_CAPABILITY_NOT_FOUND",
                    "stage": "resolve",
                },
            )

    # 1.5 Authorization Gate (B1)
    try:
        from nous_runtime.governance import (
            ActionProposal,
            AuthorizationContext,
            get_gate,
        )
        from nous_runtime.governance.runtime_mode import should_fail_closed
        import os as _os
        import getpass as _getpass

        workspace = str(_workspace_root or "").strip() or _os.getcwd()
        if not _workspace_root:
            try:
                from nous_runtime.project.workspace import find_workspace
                ws = find_workspace()
                if ws:
                    workspace = str(ws)
            except Exception:
                pass

        proposal = ActionProposal(
            action_type="capability.execute",
            capability_id=capability_id,
            target_workspace=workspace,
            side_effect_class=_infer_side_effect(capability_id),
            reversibility=_infer_reversibility(capability_id),
            parameter_summary=str(params)[:200],
            params=dict(params),
            deployment_channel=_governance_surface,
            created_at="",
        )

        if isinstance(_authorization_context, dict):
            context = AuthorizationContext.from_dict(_authorization_context)
        else:
            context = _authorization_context
        context = context or AuthorizationContext(
                subject_type="user",
                subject_id=f"{_getpass.getuser()}@{_os.environ.get('COMPUTERNAME', 'localhost')}",
                authn_method="cli_os_user",
                authn_confidence=0.8,
                session_locality="local",
            )

        gate = get_gate()
        decision = gate.evaluate(proposal, context)

        fail_closed = should_fail_closed(surface=_governance_surface)
        if decision.action_mode == "DENY":
            if fail_closed or decision.rule_class == "NON_OVERRIDABLE":
                return Observation.failure(
                    "capability.execute",
                    [f"Authorization denied: {decision.reason_message}"],
                    capability=capability_id,
                    duration_ms=(time.time() - start) * 1000,
                    metadata={
                        "provider_id": "",
                        "error_code": "NOUS_UNAUTHORIZED",
                        "stage": "authorization",
                        "gate_decision_id": decision.decision_id,
                        "gate_reason": decision.reason_code,
                    },
                )
            log.warning(
                "Governance DENY recorded but compatibility execution continues: %s",
                decision.reason_code,
            )
        elif decision.action_mode == "ASK_APPROVAL":
            if fail_closed:
                approval_request_id = ""
                try:
                    from nous_runtime.governance.broker import get_broker
                    broker = get_broker()
                    pending = next(
                        (
                            item for item in broker.get_pending()
                            if item.get("proposal_hash") == proposal.proposal_hash
                            and item.get("requested_by") == context.subject_id
                        ),
                        None,
                    )
                    if pending is None:
                        request = broker.request_approval(
                            run_id=context.request_id or f"capability-{decision.decision_id}",
                            task_id=capability_id,
                            proposal=proposal,
                            context=context,
                            requester=context.subject_id,
                            ttl_hours=1,
                        )
                        approval_request_id = request.request_id
                    else:
                        approval_request_id = str(pending.get("request_id") or "")
                except Exception as approval_error:
                    log.warning("Could not create capability approval request: %s", approval_error)
                return Observation.failure(
                    "capability.execute",
                    [f"Approval required: {decision.reason_message}"],
                    capability=capability_id,
                    duration_ms=(time.time() - start) * 1000,
                    metadata={
                        "provider_id": "",
                        "error_code": "NOUS_APPROVAL_REQUIRED",
                        "stage": "authorization",
                        "gate_decision_id": decision.decision_id,
                        "approval_required": True,
                        "approval_request_id": approval_request_id,
                        "proposal_hash": proposal.proposal_hash,
                    },
                )
            log.warning("Governance approval required but compatibility execution continues")
        elif decision.action_mode == "ESCALATE":
            if fail_closed:
                return Observation.failure(
                    "capability.execute",
                    [f"Escalated: {decision.reason_message}"],
                    capability=capability_id,
                    duration_ms=(time.time() - start) * 1000,
                    metadata={
                        "provider_id": "",
                        "error_code": "NOUS_ESCALATED",
                        "stage": "authorization",
                        "gate_decision_id": decision.decision_id,
                    },
                )
            log.warning("Governance escalation recorded but compatibility execution continues")
        # EXECUTE, RECOMMEND, or compatibility continuation: proceed
    except Exception as e:
        import logging
        from nous_runtime.governance.runtime_mode import should_fail_closed
        _log = logging.getLogger("nous.capability.resolver")
        if should_fail_closed(surface=_governance_surface):
            _log.error("Gate evaluation failed; strict governance blocks execution: %s", e)
            return Observation.failure(
                "capability.execute",
                [f"Governance gate unavailable: {e}"],
                capability=capability_id,
                duration_ms=(time.time() - start) * 1000,
                metadata={
                    "provider_id": "",
                    "error_code": "NOUS_GOVERNANCE_UNAVAILABLE",
                    "stage": "authorization",
                    "gate_bypass_blocked": True,
                },
            )
        _log.warning("Gate evaluation failed (compatibility execution): %s", e)

    # 2. v0.2.0: dispatch on the declared executor type
    if executor_type == "subprocess":
        return _execute_subprocess(
            capability_id,
            cap_meta,
            params,
            start,
            workspace_root=_workspace_root,
        )
    if executor_type == "runtime":
        try:
            from nous_runtime.capability.runtime_executor import execute_runtime_capability
            result = execute_runtime_capability(
                capability_id,
                params,
                workspace_root=workspace,
            )
            return Observation.success(
                "capability.execute",
                {"result": result},
                capability=capability_id,
                duration_ms=(time.time() - start) * 1000,
                metadata={
                    "provider_id": "nous-runtime",
                    "provider_name": "Nous Runtime service",
                    "executor_type": "runtime",
                    "execution_scope": "runtime-service",
                    "kernel_traversed": False,
                    "stage": "execute",
                },
            )
        except Exception as exc:
            return Observation.failure(
                "capability.execute",
                [str(exc)],
                capability=capability_id,
                duration_ms=(time.time() - start) * 1000,
                metadata={
                    "provider_id": "nous-runtime",
                    "error_code": "NOUS_RUNTIME_EXECUTION_FAILED",
                    "executor_type": "runtime",
                    "execution_scope": "runtime-service",
                    "kernel_traversed": False,
                    "stage": "execute",
                },
            )
    if executor_type != "provider":
        return Observation.failure(
            "capability.execute",
            [f"Executor type '{executor_type}' is not supported by this runtime"],
            capability=capability_id,
            duration_ms=(time.time() - start) * 1000,
            metadata={
                "provider_id": "",
                "provider_name": "",
                "error_code": "NOUS_EXECUTOR_UNSUPPORTED",
                "stage": "dispatch",
                "executor_type": executor_type,
            },
        )

    # 3. Execute via provider
    try:
        from nous_runtime.intelligence.reliability.executor import execute_provider_observation
        provider_obs = execute_provider_observation(
            resolution.provider_id,
            capability_id,
            payload=params,
        )
        ok = provider_obs.status == "success"
        duration_ms = (time.time() - start) * 1000
        metadata = {
            "provider_id": resolution.provider_id,
            "provider_name": resolution.provider_name,
            "error_code": "" if ok else "NOUS_EXECUTION_FAILED",
            "stage": "execute",
            "provider_observation_id": provider_obs.observation_id,
        }
        provider_metadata = provider_obs.metadata or {}
        for key in ("reliability_wrapped", "execution_id", "model_id"):
            if key in provider_metadata:
                metadata[key] = provider_metadata[key]
        if provider_metadata.get("error_code"):
            metadata["error_code"] = provider_metadata["error_code"]

        if ok:
            return Observation.success(
                "capability.execute",
                {
                    "result": provider_obs.data.get("result", provider_obs.data),
                    "provider_observation": provider_obs.summary(),
                },
                capability=capability_id,
                duration_ms=duration_ms,
                metadata=metadata,
            )
        return Observation.failure(
            "capability.execute",
            provider_obs.errors or ["execution failed"],
            capability=capability_id,
            duration_ms=duration_ms,
            metadata=metadata,
        )
    except Exception as e:
        return Observation.failure(
            "capability.execute",
            [str(e)],
            capability=capability_id,
            duration_ms=(time.time() - start) * 1000,
            metadata={
                "provider_id": resolution.provider_id,
                "provider_name": resolution.provider_name,
                "error_code": "NOUS_PROVIDER_UNAVAILABLE",
                "stage": "provider",
            },
        )


# Subprocess executor


def _execute_subprocess(
    capability_id: str,
    metadata: dict[str, Any],
    params: dict[str, Any],
    start: float,
    *,
    workspace_root: str = "",
) -> Observation:
    """Execute a subprocess-type capability declared in the registry.

    The argv comes exclusively from the registered capability metadata
    (``command`` list, or ``executable`` + ``args``) — never from caller
    params.  Placeholder argv elements of the exact form ``{name}`` are
    replaced by ``str(params[name])`` as a single argv entry; there is no
    shell, so parameter values cannot inject.
    """
    import re
    import tempfile
    import time
    from pathlib import Path

    placeholder_re = re.compile(r"^\{([a-z_][a-z0-9_]*)\}$")

    def _fail(errors: list[str], error_code: str, **extra: Any) -> Observation:
        meta: dict[str, Any] = {
            "provider_id": "",
            "provider_name": "",
            "error_code": error_code,
            "stage": "execute",
            "executor_type": "subprocess",
        }
        meta.update(extra)
        return Observation.failure(
            "capability.execute",
            errors,
            capability=capability_id,
            duration_ms=(time.time() - start) * 1000,
            metadata=meta,
        )

    # 1. Build argv from registered metadata only
    command = metadata.get("command")
    if not command and metadata.get("executable"):
        command = [metadata["executable"], *metadata.get("args", [])]
    if not isinstance(command, list) or not command:
        return _fail(
            [f"Capability '{capability_id}' declares executor_type=subprocess "
             "but no 'command' (or 'executable') in its metadata"],
            "NOUS_SUBPROCESS_MISCONFIGURED",
        )

    argv: list[str] = []
    for element in command:
        text = str(element)
        match = placeholder_re.match(text)
        if match:
            name = match.group(1)
            if name not in params:
                return _fail(
                    [f"Missing required parameter '{name}' for {capability_id}"],
                    "NOUS_SUBPROCESS_MISCONFIGURED",
                )
            argv.append(str(params[name]))
        else:
            argv.append(text)

    # 2. Timeout from the registry row, then metadata, then default
    timeout_ms = 30000
    try:
        from nous_runtime.compat.capability import get_capability

        cap = get_capability(capability_id)
        if isinstance(cap, dict) and cap.get("timeout_ms"):
            timeout_ms = int(cap["timeout_ms"])
        elif metadata.get("timeout_ms"):
            timeout_ms = int(metadata["timeout_ms"])
    except Exception:
        pass

    # 3. Run through the strict ProcessSandbox authority. This preserves the
    # immutable argv contract while adding Job Object/resource isolation and
    # an explicit network-disabled policy.  An unscoped registry invocation
    # receives a fresh empty directory instead of ambient access to the
    # caller's repository or private Runtime state.
    from nous_runtime.capability.sandbox import run_process_strict

    configured_workspace = str(workspace_root or "").strip()
    if configured_workspace:
        workspace = Path(configured_workspace).expanduser().resolve()
        if workspace.name.casefold() in {".nous", ".apeir"}:
            workspace = workspace.parent
        completed = run_process_strict(
            argv,
            cwd=str(workspace),
            timeout_seconds=max(1, timeout_ms // 1000),
            max_output_bytes=1_000_000,
        )
    else:
        with tempfile.TemporaryDirectory(prefix="apeir-capability-") as scratch:
            completed = run_process_strict(
                argv,
                cwd=scratch,
                timeout_seconds=max(1, timeout_ms // 1000),
                max_output_bytes=1_000_000,
            )
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if completed.ok:
        return Observation.success(
            "capability.execute",
            {"result": {"stdout": stdout, "stderr": stderr, "exit_code": 0}},
            capability=capability_id,
            duration_ms=(time.time() - start) * 1000,
            metadata={
                "provider_id": "",
                "provider_name": "",
                "error_code": "",
                "stage": "execute",
                "executor_type": "subprocess",
            },
        )
    return _fail(
        [f"exit code {completed.returncode}", stderr[-500:] or stdout[-500:]],
        "NOUS_SUBPROCESS_FAILED",
        exit_code=completed.returncode,
        stdout=stdout[-500:],
        stderr=stderr[-500:],
    )


# v0.2.0: Category-based side-effect / reversibility maps
# These replace prefix-based (model.*) inference.  When a capability
# declares these fields via its metadata the declared value always
# wins; the maps below are used only as a fallback.

_SIDE_EFFECT_BY_CATEGORY: dict[str, str] = {
    "model": "external_write",
    "rag": "read_only",
    "device": "local_write",
    "notification": "external_write",
    "tool": "local_write",
    "automation": "external_write",
    "software": "local_write",
    "agent": "external_write",
    "connector": "external_write",
}

_REVERSIBILITY_BY_CATEGORY: dict[str, str] = {
    "model": "reversible",
    "rag": "reversible",
    "device": "partially_reversible",
    "notification": "reversible",
    "tool": "partially_reversible",
    "automation": "partially_reversible",
    "software": "partially_reversible",
    "agent": "partially_reversible",
    "connector": "partially_reversible",
}


def _get_capability_metadata(capability_id: str) -> dict[str, Any]:
    """Return registered capability metadata, or {} if not found."""
    try:
        from nous_runtime.compat.capability import get_capability

        cap = get_capability(capability_id)
        if isinstance(cap, dict):
            meta = cap.get("metadata", {})
            return meta if isinstance(meta, dict) else {}
    except Exception:
        pass
    return {}


def _infer_side_effect(capability_id: str) -> str:
    """Infer side-effect class from declared metadata, then category, then name."""
    # 1. Check capability's declared metadata (v0.2.0)
    meta = _get_capability_metadata(capability_id)
    if meta.get("side_effect_class"):
        return str(meta["side_effect_class"])

    # 2. Check explicit keyword patterns (strong signals)
    if capability_id in ("system.echo", "system.status"):
        return "read_only"
    if "file_write" in capability_id or "write" in capability_id:
        return "local_write"
    if "shell" in capability_id or "exec" in capability_id:
        return "destructive"

    # 3. Check category-based fallback (v0.2.0)
    category = _category_for(capability_id)
    if category in _SIDE_EFFECT_BY_CATEGORY:
        return _SIDE_EFFECT_BY_CATEGORY[category]

    # 4. Conservative keyword fallback (no prefix magic)
    if "file_read" in capability_id or "read" in capability_id or "search" in capability_id:
        return "read_only"
    return "unknown"


def _infer_reversibility(capability_id: str) -> str:
    """Infer reversibility from declared metadata, then category, then name."""
    # 1. Check capability's declared metadata (v0.2.0)
    meta = _get_capability_metadata(capability_id)
    if meta.get("reversibility"):
        return str(meta["reversibility"])

    # 2. Check explicit keyword patterns (strong signals)
    if capability_id in ("system.echo", "system.status"):
        return "reversible"
    if "shell" in capability_id or "exec" in capability_id or "delete" in capability_id:
        return "irreversible"

    # 3. Check category-based fallback (v0.2.0)
    category = _category_for(capability_id)
    if category in _REVERSIBILITY_BY_CATEGORY:
        return _REVERSIBILITY_BY_CATEGORY[category]

    # 4. Conservative keyword fallback (no prefix magic)
    if "file_write" in capability_id:
        return "partially_reversible"
    return "unknown"


def _category_for(capability_id: str) -> str:
    """Return the declared category for a capability, or ''."""
    meta = _get_capability_metadata(capability_id)
    if meta.get("category"):
        return str(meta["category"])
    try:
        from nous_runtime.compat.capability import get_capability

        cap = get_capability(capability_id)
        if isinstance(cap, dict):
            return str(cap.get("category", ""))
    except Exception:
        pass
    return ""


def execute_capability(capability_id: str, **params) -> ExecutionResult:
    """
    Execute a capability through the resolver pipeline.

    This is the legacy public API. Internally the Runtime now produces
    Observation first, then adapts it to ExecutionResult for existing callers.
    New Runtime code should prefer execute_capability_observation().
    """
    observation = execute_capability_observation(capability_id, **params)
    return ExecutionResult.from_observation(observation)

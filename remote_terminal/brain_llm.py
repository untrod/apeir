"""Remote Terminal model client routed exclusively through Nous Gateway.

⚠️ DEPRECATED: This module is a compat shim. All model calls already route
through ModelGatewayFacade (via model_gateway_bridge). This compat layer will
be removed once all callers use nous_runtime.provider.adapters directly.
"""

from __future__ import annotations

import logging
import os
import warnings
from collections.abc import Callable, Mapping, Sequence
from typing import Any

try:
    import config as _config
    import crypto as _crypto
    import brain_utils as _utils
    import model_gateway_bridge as _gateway
except ImportError:
    from remote_terminal import brain_utils as _utils
    from remote_terminal import config as _config
    from remote_terminal import crypto as _crypto
    from remote_terminal import model_gateway_bridge as _gateway


_log = logging.getLogger("brain")
_PARSE_WORKER_RUNNING = False

# Legacy path metrics (incremented on every compat invocation)
legacy_model_call_total: int = 0
legacy_ingest_model_call_total: int = 0
legacy_stream_model_call_total: int = 0

_DEPRECATION_MESSAGE = (
    "brain_llm.call_model() is a legacy compat path. "
    "Use nous_runtime.model_runtime.gateway.ModelGateway.invoke() directly, "
    "or nous_runtime.provider.adapters.* for provider-specific calls."
)


def call_model(
    convo: Sequence[Mapping[str, Any]],
    model: str | None,
    use_tools: bool = True,
    tool_defs: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Invoke the configured model through ``ModelGatewayFacade``.

    ⚠️ DEPRECATED: Routes through model_gateway_bridge (unified Gateway).
    This compat entry point emits DeprecationWarning and increments
    legacy_model_call_total. No second execution path exists.
    """
    warnings.warn(_DEPRECATION_MESSAGE, DeprecationWarning, stacklevel=2)
    global legacy_model_call_total
    legacy_model_call_total += 1

    api_key = _crypto.load_api_key()
    if not api_key:
        raise RuntimeError(
            "LLM credential is not configured. Configure it before use."
        )
    selected_model = str(model or _config.LLM_MODEL)
    tools = tuple(tool_defs or ()) if use_tools else ()
    result = _gateway.invoke_message(
        convo,
        endpoint=str(_config.LLM_API_URL),
        api_key=api_key,
        model=selected_model,
        timeout_s=float(_config.LLM_TIMEOUT),
        tools=tools,
        max_tokens=_configured_max_tokens(),
    )
    _record_gateway_usage(result)
    return dict(result.message)


def call_ingest_model(
    convo: Sequence[Mapping[str, Any]],
    model: str | None = None,
    use_tools: bool = False,
    tool_defs: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Use the optional ingest model through the same Gateway boundary.

    ⚠️ DEPRECATED: Routes through model_gateway_bridge.
    Emits DeprecationWarning and increments legacy_ingest_model_call_total.
    """
    warnings.warn(
        "brain_llm.call_ingest_model() is a legacy compat path.",
        DeprecationWarning, stacklevel=2,
    )
    global legacy_ingest_model_call_total
    legacy_ingest_model_call_total += 1
    endpoint = str(getattr(_config, "INGEST_API_URL", "") or "")
    api_key = str(getattr(_config, "INGEST_API_KEY", "") or "")
    selected_model = str(
        model or getattr(_config, "INGEST_MODEL", "") or ""
    )
    if not (endpoint and api_key and selected_model):
        return call_model(convo, None, False)
    result = _gateway.invoke_message(
        convo,
        endpoint=endpoint,
        api_key=api_key,
        model=selected_model,
        timeout_s=float(_config.LLM_TIMEOUT),
        tools=tuple(tool_defs or ()) if use_tools else (),
        max_tokens=_configured_max_tokens(),
    )
    _record_gateway_usage(result)
    return dict(result.message)


def call_model_stream(
    convo: Sequence[Mapping[str, Any]],
    model: str | None,
    use_tools: bool,
    on_content_delta: Callable[[str], Any],
    tool_defs: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Preserve the streaming callback contract over the Gateway facade.

    ⚠️ DEPRECATED: Delegates to call_model() (which routes through Gateway).
    Emits DeprecationWarning and increments legacy_stream_model_call_total.

    The current Provider adapters return a normalized complete response.  The
    callback receives that response as one delta until a native streaming
    adapter is configured.
    """
    warnings.warn(
        "brain_llm.call_model_stream() is a legacy compat path.",
        DeprecationWarning, stacklevel=2,
    )
    global legacy_stream_model_call_total
    legacy_stream_model_call_total += 1
    message = call_model(
        convo,
        model,
        use_tools=use_tools,
        tool_defs=tool_defs,
    )
    content = message.get("content")
    if content:
        on_content_delta(str(content))
    return message


def parse_pending_worker() -> None:
    """Parse pending documents with the Gateway-backed ingest model."""
    global _PARSE_WORKER_RUNNING
    try:
        try:
            import doc_engine
            import learn_db
        except ImportError:
            from remote_terminal import doc_engine, learn_db

        while True:
            pending = learn_db.list_pending_docs(limit=1)
            if not pending:
                break
            document = pending[0]
            filepath = document.get("filepath") or os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "learn_docs",
                document["filename"],
            )
            if not os.path.isfile(filepath):
                learn_db.update_document_status(
                    document["id"],
                    "error",
                    note="source document is missing",
                )
                continue
            try:
                taxonomy = learn_db.taxonomy_values()
                with doc_engine._INGEST_LOCK:
                    doc_engine.process_document(
                        filepath,
                        call_ingest_model,
                        subject=document.get("subject", ""),
                        doc_type=document.get("doc_type", ""),
                        stage=document.get("stage", ""),
                        taxonomy=taxonomy,
                    )
            except Exception as exc:
                _log.error(
                    "document ingest failed for %s: %s",
                    document.get("filename"),
                    exc,
                )
                try:
                    learn_db.update_document_status(
                        document["id"],
                        "error",
                        note=str(exc)[:200],
                    )
                except Exception:
                    pass
    finally:
        _PARSE_WORKER_RUNNING = False


def is_parse_worker_running() -> bool:
    return _PARSE_WORKER_RUNNING


def set_parse_worker_running(value: bool) -> None:
    global _PARSE_WORKER_RUNNING
    _PARSE_WORKER_RUNNING = bool(value)


def _configured_max_tokens() -> int:
    try:
        return int(_config._get("LLM_MAX_TOKENS", "4096"))
    except Exception:
        return 4096


def _record_gateway_usage(result: _gateway.RemoteModelResult) -> None:
    usage = dict(result.usage)
    prompt_tokens = int(
        usage.get("prompt_tokens")
        or usage.get("input_tokens")
        or 0
    )
    completion_tokens = int(
        usage.get("completion_tokens")
        or usage.get("output_tokens")
        or 0
    )
    _utils.record_usage(
        result.model_id,
        prompt_tokens,
        completion_tokens,
    )

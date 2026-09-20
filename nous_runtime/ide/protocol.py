"""Editor-neutral IDE Runtime Protocol over authoritative Runtime contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class IDERequest:
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    subject_id: str = ""


@dataclass(frozen=True)
class IDEResponse:
    ok: bool
    data: Any = None
    error: str = ""


class IDERuntimeProtocol:
    """Stateless adapter used by editor integrations; Server Runtime remains authoritative."""

    def __init__(self, root: str = ".") -> None:
        self.root = root

    def handle(self, request: IDERequest) -> IDEResponse:
        try:
            return IDEResponse(True, self._dispatch(request))
        except (KeyError, ValueError) as exc:
            return IDEResponse(False, error=str(exc))
        except Exception as exc:
            return IDEResponse(False, error=f"IDE Runtime action failed: {type(exc).__name__}")

    def _dispatch(self, request: IDERequest) -> Any:
        action = request.action
        params = request.params
        if action == "runtime.status":
            from nous_runtime.runtime.lifecycle import Runtime

            return Runtime().status().__dict__
        if action == "run.list":
            return [item.to_dict() for item in self._events().list_runs(limit=int(params.get("limit") or 20))]
        if action == "run.show":
            run_id = str(params.get("run_id") or "")
            record = self._events().get_run(run_id)
            if record is None:
                raise KeyError(f"Run not found: {run_id}")
            events = [item.to_dict() for item in self._events().iter_persisted_events(run_id, limit=200)]
            return {"run": record.to_dict(), "events": events}
        if action == "provider.list":
            from nous_runtime.cli.provider_experience import configured_provider_rows

            return [_safe_provider(item) for item in configured_provider_rows(self.root)]
        if action == "approval.list":
            from nous_runtime.governance.broker import get_broker

            return get_broker().get_pending()
        if action == "approval.resolve":
            return self._resolve_approval(request)
        if action in {"editor.explain", "editor.review", "editor.optimize", "editor.refactor", "editor.tests"}:
            from nous_runtime.capability.resolver import execute_capability

            capability = "model.code" if action != "editor.explain" else "model.reason"
            result = execute_capability(capability, prompt=str(params.get("prompt") or ""))
            return {"ok": result.ok, "result": result.result, "error": result.error}
        raise ValueError(f"Unsupported IDE action: {action}")

    def _resolve_approval(self, request: IDERequest) -> dict[str, Any]:
        from nous_runtime.governance.broker import get_broker

        request_id = str(request.params.get("request_id") or "")
        decision = str(request.params.get("decision") or "").lower()
        if not request.subject_id:
            raise ValueError("IDE approval requires an authenticated subject")
        if decision == "approve":
            response = get_broker().approve(
                request_id,
                approver_id=request.subject_id,
                scope="once",
                prevent_self_approval=True,
            )
        elif decision == "reject":
            response = get_broker().deny(request_id, approver_id=request.subject_id)
        else:
            raise ValueError("IDE approval decision must be approve or reject")
        return response.to_dict()

    def _events(self):
        from nous_runtime.events import EventStream

        return EventStream(self.root)


def _safe_provider(item: dict[str, Any]) -> dict[str, Any]:
    result = dict(item)
    credential = result.get("credential")
    if credential is not None:
        result["credential"] = credential.__dict__
    return result

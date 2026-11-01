"""Real Workflow/Gateway/accounting; simulated NKI bytes, no live model calls."""

import copy
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from nous_runtime.agent.session import AgentSessionStore
from nous_runtime.events.bus import reset_event_bus
from nous_runtime.governance.contracts import AuthorizationContext
from nous_runtime.governance.permission import PermissionEngine, PermissionRule
from nous_runtime.model_runtime.facade import (
    GatewayExecutionContext,
    GatewayOperation,
    GatewayRequest,
    ModelGatewayFacade,
)
from nous_runtime.model_runtime.factory import build_gateway_from_providers
from nous_runtime.workflow import WorkflowDefinition, WorkflowRuntime, WorkflowStep
from nous_runtime.workflow.model_host import (
    MODEL_ACTION,
    bind_model_host,
    validate_model_step,
)
from nous_runtime.workflow.models import StepType, TriggerType
from tests.control_plane.test_human_sessions import human_env as human_env, login
from tests.model_runtime.test_gateway_accounting import fake_kernel_receipt
from tests.model_runtime.test_kernel_execution_gateway import (
    LocalOpenAIProvider,
    RemoteProvider,
)


class KernelJournalFixture:
    """Protocol fixture only; do not label this a real Kernel/model qualification."""

    def __init__(self):
        self.receipts = {}
        self.operations = []
        self.queries = []
        self.lose_response = False
        self.hide_receipt = False
        self.before_dispatch = lambda: None

    async def execute_operation(self, operation, idempotency_key=""):
        key = operation["workload_id"]
        if key not in self.receipts:
            self.before_dispatch()
            self.operations.append(copy.deepcopy(operation))
            answer = (
                "review-result"
                if operation["snapshot"]["provider_revision"].startswith("ollama-")
                else "analysis-result"
            )
            self.receipts[key] = fake_kernel_receipt(
                operation,
                {
                    "schema_version": 1,
                    "content": json.dumps({"answer": answer}),
                    "usage": {"input_tokens": 9, "output_tokens": 4},
                    "finish_reason": "stop",
                },
            )
            if self.lose_response:
                self.lose_response = False
                raise ConnectionError("fake response loss after original commit")
        return copy.deepcopy(self.receipts[key])

    async def _request(self, command, selector):
        assert command == "ExplainExecution"
        self.queries.append(dict(selector))
        receipt = self.receipts.get(selector["workload_id"])
        return {
            **selector,
            "facts": []
            if self.hide_receipt or not receipt
            else [
                {
                    "object_type": "StepCommit",
                    "object_id": receipt["operation_id"],
                    "phase": "COMMITTED",
                    "fact": {k: v for k, v in receipt.items() if k != "result"},
                }
            ],
        }

    async def close(self):
        pass


@pytest.fixture
def host(tmp_path, monkeypatch, human_env):
    gate, auth, client, _ = human_env
    _, context = login(auth, client)
    auth.permissions = PermissionEngine(
        (PermissionRule(context.subject_id, "governance.approve", "workflow:*"),)
    )
    monkeypatch.setattr("nous_runtime.governance.get_gate", lambda: gate)
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("APEIR_STATE_DIR", str(tmp_path / "accounting"))
    pricing = tmp_path / "prices.json"
    pricing.write_text(
        json.dumps(
            {
                "models": {
                    f"{provider}/deepseek-chat": {
                        "input_per_million_usd": 1,
                        "output_per_million_usd": 2,
                    }
                    for provider in ("deepseek", "ollama")
                }
            }
        )
    )
    monkeypatch.setenv("APEIR_MODEL_PRICING_FILE", str(pricing))
    journal = KernelJournalFixture()
    gateways = []

    def factory():
        gateway = build_gateway_from_providers(
            [RemoteProvider(), LocalOpenAIProvider()]
        )

        async def available():
            return True

        async def new_client():
            return journal

        gateway._ensure_nki_available = available
        gateway._new_nki_client = new_client
        gateways.append(gateway)
        return ModelGatewayFacade(gateway)

    def runtime(identity=context):
        return bind_model_host(
            WorkflowRuntime(str(tmp_path)), identity, gateway_factory=factory
        )

    reset_event_bus()
    yield SimpleNamespace(
        root=tmp_path,
        runtime=runtime,
        context=context,
        auth=auth,
        journal=journal,
        gateways=gateways,
        gate=gate,
        facade_factory=factory,
    )
    for gateway in gateways:
        gateway.close_sync_bridge()
    reset_event_bus()


def model_step(step_id="analyze", model_id="deepseek/deepseek-chat", **kwargs):
    return WorkflowStep(
        step_id,
        StepType.AGENT,
        action=MODEL_ACTION,
        approval_required=True,
        params={
            "model_id": model_id,
            "instruction": "Analyze the approved input",
            "max_tokens": 128,
            "max_cost_usd": 0.01,
            "response_schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
        },
        **kwargs,
    )


def start(host, *steps):
    runtime = host.runtime()
    definition = WorkflowDefinition(
        "model.review", "1", TriggerType.MANUAL, steps or (model_step(),)
    )
    runtime.register(definition)
    run = runtime.start(
        definition.workflow_id, definition.version, idempotency_key="original"
    )
    assert run.state.value == "waiting_approval"
    assert host.journal.operations == []
    return runtime, run


def test_two_explicit_models_consume_bound_data_and_recover_original_history(host):
    second = model_step(
        "review",
        "ollama/deepseek-chat",
        depends_on=("analyze",),
        data_bindings={
            "schema_version": 1,
            "inputs": {
                "input": {
                    "source": "step",
                    "step_id": "analyze",
                    "pointer": "/structured_output",
                }
            },
        },
    )
    runtime, run = start(host, model_step(), second)
    waiting = runtime.resume(run.run_id, approved_steps=("analyze",))
    assert waiting.state.value == "waiting_approval", waiting.error
    assert len(host.journal.operations) == 1
    completed = runtime.resume(run.run_id, approved_steps=("review",))
    assert completed.state.value == "completed", completed.error
    assert completed.outputs["review"]["structured_output"] == {
        "answer": "review-result"
    }
    assert completed.outputs["analyze"]["provider_id"] == "deepseek"
    assert completed.outputs["review"]["provider_id"] == "ollama"
    assert completed.outputs["review"]["cost_usd"] is not None
    actual_input = json.loads(host.journal.operations[1]["input"])["messages"][-1][
        "content"
    ]
    assert "analysis-result" in actual_input
    restored = host.runtime().resume(run.run_id)
    assert restored.run_id == run.run_id and restored.outputs == completed.outputs
    assert len(host.journal.operations) == 2
    assert len(AgentSessionStore(host.root).list()) == 2


@pytest.mark.parametrize(
    "missing", [None, "kernel_receipt", "accounting", "session_and_accounting"]
)
def test_response_loss_reconciles_original_or_blocks_without_a_new_model(host, missing):
    runtime, run = start(host)
    host.journal.lose_response = True
    uncertain = runtime.resume(run.run_id, approved_steps=("analyze",))
    assert uncertain.state.value == "unknown", uncertain.error
    assert len(host.journal.operations) == 1
    if missing == "kernel_receipt":
        host.journal.hide_receipt = True
    if missing in {"accounting", "session_and_accounting"}:
        for path in (host.root / "accounting").glob("usage.sqlite3*"):
            path.unlink()
    if missing == "session_and_accounting":
        for path in (host.root / ".nous").glob("agent_sessions.db*"):
            path.unlink()
    recovered = host.runtime().resume(run.run_id)
    assert recovered.run_id == run.run_id
    assert recovered.state.value == ("completed" if missing is None else "unknown"), (
        recovered.error
    )
    assert len(host.journal.operations) == 1
    if missing is None:
        assert recovered.outputs["analyze"]["structured_output"] == {
            "answer": "analysis-result"
        }
        assert host.journal.queries


@pytest.mark.parametrize("identity", ["serialized", "revoked"])
def test_model_dispatch_requires_current_original_human_authority(host, identity):
    runtime, run = start(host)
    context = host.context
    if identity == "serialized":
        context = AuthorizationContext.from_dict(context.to_dict())
    else:
        host.auth.logout(context)
    denied = host.runtime(context).resume(run.run_id, approved_steps=("analyze",))
    assert denied.state.value == "failed"
    assert "current human" in denied.error
    assert host.journal.operations == []


def test_model_binding_cannot_change_selection_or_budget():
    for target in ("model_id", "max_cost_usd", "max_tokens", "instruction"):
        step = model_step(
            data_bindings={
                "schema_version": 1,
                "inputs": {target: {"source": "inputs", "pointer": "/untrusted"}},
            }
        )
        with pytest.raises(ValueError, match="not model identity or budgets"):
            validate_model_step(step)


def test_original_gateway_request_id_is_stable_and_defaults_remain_fresh():
    request = GatewayRequest(
        GatewayOperation.CHAT,
        GatewayExecutionContext("task"),
        request_id="modelreq_" + "a" * 64,
    )
    assert (
        request.to_model_request().request_id == request.to_model_request().request_id
    )
    fresh = replace(request, request_id="")
    assert fresh.to_model_request().request_id != fresh.to_model_request().request_id


def test_studio_commits_original_human_approval_before_model_dispatch(
    host, monkeypatch
):
    from nous_runtime.api.workflow_routes import handle_workflow_run_action
    from nous_runtime.compat.capability import register_capability

    register_capability(
        "project.read_file",
        risk="low",
        requires_auth=False,
        side_effect_class="read_only",
        reversibility="reversible",
        locality="local",
        idempotent=True,
        model_uncertainty=0,
    )
    host.gate.permission_engine = PermissionEngine(
        (
            PermissionRule(
                host.context.subject_id,
                "workspace.read",
                str(host.root / ".nous" / "workflows.db"),
            ),
        )
    )
    monkeypatch.setattr(
        "nous_runtime.workflow.model_host.ModelGatewayFacade", host.facade_factory
    )
    _, run = start(host)

    def committed_approval():
        assert any(
            event["event_type"] == "workflow.approval.accepted"
            for event in host.gate.store.operation_audit()
        ), "The model must not execute inside an uncommitted approval transaction"

    host.journal.before_dispatch = committed_approval
    result = handle_workflow_run_action(
        run.run_id,
        {
            "action": "approve",
            "step_id": "analyze",
            "definition_digest": run.definition_digest,
        },
        authorization_context=host.context,
    )
    assert result["ok"], result
    assert result["data"]["state"] == "completed", result
    assert result["data"]["run_id"] == run.run_id
    assert len(host.journal.operations) == 1

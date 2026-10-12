"""Workflow admission, uncertainty, and exact-binding regressions."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
import subprocess
import sys
import threading

import pytest

from nous_runtime.workflow import (
    StepType,
    TriggerType,
    WorkflowDefinition,
    WorkflowRuntime,
    WorkflowStep,
)
from nous_runtime.capability.contract import (
    CapabilityContract,
    Idempotency,
    RetryStrategy,
)
from nous_runtime.events import EventStream, RunState
from nous_runtime.governance.operation_contracts import GovernanceApprovalRequired
from nous_runtime.workflow.models import (
    WorkflowHandlerPolicy,
    WorkflowRun,
    WorkflowState,
)
from nous_runtime.workflow.store import WorkflowBindingError, WorkflowConflictError


def definition(*steps, workflow_id="safe.workflow", version="1"):
    return WorkflowDefinition(workflow_id, version, TriggerType.MANUAL, tuple(steps))


def policy(
    *,
    capability_id="effect",
    effect="none",
    idempotency=Idempotency.IDEMPOTENT,
    retries=2,
    strategy=RetryStrategy.LINEAR,
    reconcile=False,
):
    return WorkflowHandlerPolicy(
        contract=CapabilityContract(
            capability_id=capability_id,
            side_effect_class=effect,
            idempotency=idempotency,
            retry_strategy=strategy,
            max_retries=retries,
        ),
        reconcile_started=reconcile,
    )


def test_effect_then_error_is_not_replayed_by_retry_or_restart(tmp_path):
    calls = []

    def mutate(step, context):
        calls.append(context["run_id"])
        (tmp_path / "effect.txt").write_text(str(len(calls)), encoding="utf-8")
        raise RuntimeError("response lost after effect")

    spec = definition(WorkflowStep("write", StepType.CAPABILITY, "mutate", retries=3))
    runtime = WorkflowRuntime(str(tmp_path), handlers={"mutate": mutate})
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version, idempotency_key="once")
    assert calls == [run.run_id]
    assert run.state.value == "unknown"
    restarted = WorkflowRuntime(str(tmp_path), handlers={"mutate": mutate})
    assert restarted.resume(run.run_id).state.value == "unknown"
    assert (
        restarted.start(spec.workflow_id, spec.version, idempotency_key="once").run_id
        == run.run_id
    )
    assert calls == [run.run_id]


def test_step_admission_is_persisted_before_handler_and_keeps_owned_progress(tmp_path):
    runtime = WorkflowRuntime(str(tmp_path))

    def apply(step, context):
        checkpoint = runtime.store.checkpoints(context["run_id"])[step.step_id]
        assert checkpoint["status"] == "started"
        assert checkpoint["binding_digest"]
        runtime.store.checkpoint(
            context["run_id"], "apply:effects", {"file": "complete"}
        )
        return {"ok": True}

    runtime.handlers["apply"] = apply
    spec = definition(WorkflowStep("apply", StepType.CAPABILITY, "apply"))
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version)
    assert run.state.value == "completed"
    assert runtime.store.checkpoints(run.run_id)["apply:effects"] == {
        "file": "complete"
    }


def test_same_definition_version_and_idempotency_key_reject_changed_bindings(tmp_path):
    runtime = WorkflowRuntime(str(tmp_path))
    spec = definition(
        WorkflowStep("pure", StepType.TRANSFORM, params={"value": "original"})
    )
    runtime.register(spec)
    runtime.register(spec)
    with pytest.raises(ValueError, match="definition.*changed|immutable"):
        runtime.register(
            replace(spec, steps=(replace(spec.steps[0], params={"value": "changed"}),))
        )
    run = runtime.start(
        spec.workflow_id, spec.version, {"value": 1}, idempotency_key="same"
    )
    assert (
        runtime.start(
            spec.workflow_id, spec.version, {"value": 1}, idempotency_key="same"
        ).run_id
        == run.run_id
    )
    with pytest.raises(ValueError, match="binding|inputs|idempotency"):
        runtime.start(
            spec.workflow_id, spec.version, {"value": 2}, idempotency_key="same"
        )
    next_version = replace(spec, version="2")
    runtime.register(next_version)
    with pytest.raises(ValueError, match="binding|version|idempotency"):
        runtime.start(
            spec.workflow_id, next_version.version, {"value": 1}, idempotency_key="same"
        )


def test_concurrent_pending_start_executes_original_step_once(tmp_path):
    calls = []
    admitted = threading.Barrier(2)
    spec = definition(WorkflowStep("effect", StepType.CAPABILITY, "mutate"))
    WorkflowRuntime(str(tmp_path)).register(spec)

    def start(_):
        runtime = WorkflowRuntime(
            str(tmp_path),
            handlers={
                "mutate": lambda step, context: (
                    calls.append(context["run_id"]) or {"done": True}
                )
            },
        )
        original = runtime.store.create_run

        def hold(run):
            created = original(run)
            admitted.wait(timeout=5)
            return created

        runtime.store.create_run = hold
        return runtime.start(spec.workflow_id, spec.version, idempotency_key="one")

    with ThreadPoolExecutor(max_workers=2) as executor:
        runs = list(executor.map(start, (0, 1)))
    assert runs[0].run_id == runs[1].run_id
    assert calls == [runs[0].run_id]
    assert all(run.state.value == "completed" for run in runs)


def test_cancel_during_step_fences_dependent_effect_and_survives_restart(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    effects = []

    def hold(step, context):
        entered.set()
        assert release.wait(timeout=5)
        return {"done": True}

    runtime = WorkflowRuntime(
        str(tmp_path),
        handlers={
            "hold": hold,
            "mutate": lambda step, context: effects.append("effect") or {},
        },
    )
    spec = definition(
        WorkflowStep("hold", StepType.CAPABILITY, "hold"),
        WorkflowStep("write", StepType.CAPABILITY, "mutate", ("hold",)),
    )
    runtime.register(spec)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(runtime.start, spec.workflow_id, spec.version)
        assert entered.wait(timeout=5)
        run_id = runtime.store.history(spec.workflow_id)[0].run_id
        try:
            WorkflowRuntime(str(tmp_path)).cancel(run_id)
        finally:
            release.set()
        run = future.result(timeout=5)
    assert effects == []
    assert run.cancellation_requested
    assert run.state.value == "cancelled"
    assert (
        WorkflowRuntime(str(tmp_path)).store.get_run(run_id).state.value == "cancelled"
    )


@pytest.mark.parametrize(
    "effect", ["none", "read_only", "local_write", "external_write"]
)
def test_trusted_idempotent_retry_is_bounded_and_does_not_reset_on_resume(
    tmp_path, effect
):
    calls = []

    def fail(step, context):
        calls.append(context["run_id"])
        raise RuntimeError("declared safe retry")

    spec = definition(WorkflowStep("safe", StepType.CAPABILITY, "safe", retries=5))
    policies = {"safe": policy(capability_id="safe", effect=effect, retries=1)}
    runtime = WorkflowRuntime(
        str(tmp_path), handlers={"safe": fail}, handler_policies=policies
    )
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version)
    assert len(calls) == 2
    assert runtime.store.checkpoints(run.run_id)["safe"]["attempts"] == 2
    resumed = WorkflowRuntime(
        str(tmp_path), handlers={"safe": fail}, handler_policies=policies
    ).resume(run.run_id)
    assert len(calls) == 2
    assert resumed.state is (
        WorkflowState.FAILED
        if effect in {"none", "read_only"}
        else WorkflowState.UNKNOWN
    )


@pytest.mark.parametrize(
    "trusted",
    [
        policy(effect="external_write", idempotency=Idempotency.CONDITIONAL),
        policy(effect="external_write", idempotency=Idempotency.NOT_IDEMPOTENT),
        policy(effect="unknown"),
        policy(effect="destructive"),
        policy(effect="local_write", strategy=RetryStrategy.NONE),
    ],
)
def test_unsupported_effects_and_conditional_idempotency_cannot_retry(
    tmp_path, trusted
):
    calls = []

    def fail(step, context):
        calls.append("effect")
        raise RuntimeError("possible effect")

    spec = definition(
        WorkflowStep(
            "effect",
            StepType.CAPABILITY,
            "effect",
            retries=4,
            params={"idempotent": True, "reconcile_started": True},
        )
    )
    runtime = WorkflowRuntime(
        str(tmp_path), handlers={"effect": fail}, handler_policies={"effect": trusted}
    )
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version)
    assert run.state is WorkflowState.UNKNOWN
    assert runtime.resume(run.run_id).state is WorkflowState.UNKNOWN
    assert calls == ["effect"]


def test_model_params_cannot_enable_retry_or_journal_reconciliation(tmp_path):
    calls = []

    def effect(step, context):
        calls.append("effect")
        raise RuntimeError("uncertain")

    spec = definition(
        WorkflowStep(
            "effect",
            StepType.CAPABILITY,
            "effect",
            retries=3,
            params={
                "idempotency": "idempotent",
                "handler_policy": {"reconcile_started": True},
            },
        )
    )
    runtime = WorkflowRuntime(str(tmp_path), handlers={"effect": effect})
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version)
    assert (
        runtime.resume(run.run_id, approved_steps=("effect",)).state
        is WorkflowState.UNKNOWN
    )
    assert calls == ["effect"]
    assert (
        EventStream(str(tmp_path)).get_run(run.run_id).state
        is RunState.RECOVERY_REQUIRED
    )


def test_process_death_after_effect_restores_started_marker_without_replay(tmp_path):
    script = """
import os, sys
from pathlib import Path
from nous_runtime.workflow import WorkflowRuntime, WorkflowDefinition, WorkflowStep, StepType, TriggerType
root = Path(sys.argv[1])
def effect(step, context):
    (root / 'effect.txt').write_text('one', encoding='utf-8')
    os._exit(0)
runtime = WorkflowRuntime(str(root), handlers={'effect': effect})
runtime.register(WorkflowDefinition('hard.restart', '1', TriggerType.MANUAL, (WorkflowStep('effect', StepType.CAPABILITY, 'effect', retries=3),)))
runtime.start('hard.restart', '1', idempotency_key='original')
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        env={**os.environ, "PYTHONPATH": str(__import__("pathlib").Path.cwd())},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    calls = []
    runtime = WorkflowRuntime(
        str(tmp_path),
        handlers={"effect": lambda step, context: calls.append("replayed") or {}},
    )
    run = runtime.store.history("hard.restart")[0]
    assert (tmp_path / "effect.txt").read_text(encoding="utf-8") == "one"
    assert runtime.store.checkpoints(run.run_id)["effect"]["status"] == "started"
    assert runtime.resume(run.run_id).state is WorkflowState.UNKNOWN
    assert runtime.resume(run.run_id).state is WorkflowState.UNKNOWN
    assert calls == []


@pytest.mark.parametrize("state", [WorkflowState.RUNNING, WorkflowState.FAILED])
def test_legacy_started_or_failed_run_cannot_gain_replay_on_second_resume(
    tmp_path, state
):
    calls = []
    spec = definition(WorkflowStep("effect", StepType.CAPABILITY, "effect", retries=3))
    runtime = WorkflowRuntime(
        str(tmp_path),
        handlers={"effect": lambda step, context: calls.append("replay") or {}},
    )
    runtime.register(spec)
    run = runtime.store.create_run(WorkflowRun(spec.workflow_id, spec.version, {}))
    value = runtime.store._run_dict(run)
    for field in ("definition_digest", "inputs_digest", "revision"):
        value.pop(field)
    value["state"] = state.value
    if state is WorkflowState.FAILED:
        value["step_states"] = {"effect": "failed"}
        runtime.store.checkpoint(
            run.run_id, "effect", {"status": "failed", "error": "old response lost"}
        )
    with runtime.store._db() as db:
        db.execute(
            "UPDATE workflow_runs SET state=?, run_json=? WHERE run_id=?",
            (state.value, json.dumps(value), run.run_id),
        )
    assert runtime.resume(run.run_id).state is WorkflowState.UNKNOWN
    assert runtime.resume(run.run_id).state is WorkflowState.UNKNOWN
    assert calls == []


def test_host_journal_reconciles_original_step_and_preserves_effect_progress(tmp_path):
    runtime = WorkflowRuntime(str(tmp_path))
    calls = []
    effects = []

    def reconcile(step, context):
        calls.append(context["run_id"])
        if runtime.store.checkpoints(context["run_id"]).get("apply:effects"):
            return {"work_id": "original-work", "reconciled": True}
        effects.append("one")
        runtime.store.checkpoint(
            context["run_id"],
            "apply:effects",
            {"work_id": "original-work", "files": ["source.py"]},
        )
        raise RuntimeError("response lost after journaled effect")

    host_policies = {"apply": WorkflowHandlerPolicy(reconcile_started=True)}
    runtime = WorkflowRuntime(
        str(tmp_path), handlers={"apply": reconcile}, handler_policies=host_policies
    )
    spec = definition(WorkflowStep("apply", StepType.CAPABILITY, "apply", retries=4))
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version)
    assert run.state is WorkflowState.FAILED
    assert calls == [run.run_id]
    restarted = WorkflowRuntime(
        str(tmp_path), handlers={"apply": reconcile}, handler_policies=host_policies
    )
    resumed = restarted.resume(run.run_id)
    assert resumed.state is WorkflowState.COMPLETED
    assert calls == [run.run_id, run.run_id]
    assert effects == ["one"]
    assert resumed.outputs["apply"]["work_id"] == "original-work"
    assert restarted.store.checkpoints(run.run_id)["apply:effects"]["files"] == [
        "source.py"
    ]


def test_changed_host_policy_after_dispatch_cannot_enable_replay(tmp_path):
    calls = []

    def effect(step, context):
        calls.append("effect")
        raise RuntimeError("uncertain")

    spec = definition(WorkflowStep("effect", StepType.CAPABILITY, "effect", retries=3))
    runtime = WorkflowRuntime(str(tmp_path), handlers={"effect": effect})
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version)
    restarted = WorkflowRuntime(
        str(tmp_path),
        handlers={"effect": effect},
        handler_policies={"effect": policy(effect="local_write", reconcile=True)},
    )
    assert restarted.resume(run.run_id).state is WorkflowState.UNKNOWN
    assert calls == ["effect"]


def test_completion_persistence_loss_leaves_original_started_step_unreplayed(
    tmp_path, monkeypatch
):
    calls = []
    runtime = WorkflowRuntime(
        str(tmp_path),
        handlers={
            "effect": lambda step, context: calls.append("effect") or {"done": True}
        },
    )
    spec = definition(WorkflowStep("effect", StepType.CAPABILITY, "effect", retries=3))
    runtime.register(spec)
    monkeypatch.setattr(
        runtime.store,
        "finish_step",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("checkpoint response lost")
        ),
    )
    run = runtime.start(spec.workflow_id, spec.version)
    assert run.state is WorkflowState.UNKNOWN
    restarted = WorkflowRuntime(str(tmp_path), handlers=runtime.handlers)
    assert restarted.store.checkpoints(run.run_id)["effect"]["status"] == "started"
    assert restarted.resume(run.run_id).state is WorkflowState.UNKNOWN
    assert calls == ["effect"]


def test_admission_persistence_failure_prevents_handler(tmp_path, monkeypatch):
    calls = []
    runtime = WorkflowRuntime(
        str(tmp_path),
        handlers={"effect": lambda step, context: calls.append("effect") or {}},
    )
    spec = definition(WorkflowStep("effect", StepType.CAPABILITY, "effect"))
    runtime.register(spec)
    monkeypatch.setattr(
        runtime.store,
        "admit_step",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("cannot persist admission")
        ),
    )
    assert runtime.start(spec.workflow_id, spec.version).state is WorkflowState.UNKNOWN
    assert calls == []


def test_original_governance_approval_is_not_a_retry_or_an_approved_steps_bypass(
    tmp_path,
):
    requests = []

    def governed(step, context):
        requests.append(context["run_id"])
        raise GovernanceApprovalRequired(
            {"work_id": "original-work", "approval_request_id": "original-approval"}
        )

    runtime = WorkflowRuntime(str(tmp_path), handlers={"governed": governed})
    spec = definition(
        WorkflowStep("effect", StepType.CAPABILITY, "governed", retries=4)
    )
    runtime.register(spec)
    run = runtime.start(
        spec.workflow_id,
        spec.version,
        {"_agent_session_id": "original-session"},
        idempotency_key="original",
    )
    assert run.state is WorkflowState.WAITING_APPROVAL
    assert runtime.store.checkpoints(run.run_id)["effect"]["attempts"] == 0
    resumed = runtime.resume(run.run_id, approved_steps=("effect",))
    assert resumed.state is WorkflowState.WAITING_APPROVAL
    assert resumed.outputs["effect"]["approval_request_id"] == "original-approval"
    assert requests == [run.run_id, run.run_id]
    assert (
        runtime.start(
            spec.workflow_id,
            spec.version,
            {"_agent_session_id": "original-session"},
            idempotency_key="original",
        ).run_id
        == run.run_id
    )
    with pytest.raises(WorkflowBindingError):
        runtime.start(
            spec.workflow_id,
            spec.version,
            {"_agent_session_id": "other-session"},
            idempotency_key="original",
        )


def test_parallel_completion_is_checkpointed_before_approval_pause(tmp_path):
    calls = []
    runtime = WorkflowRuntime(
        str(tmp_path),
        handlers={
            "effect": lambda step, context: calls.append("one") or {"done": True}
        },
    )
    spec = definition(
        WorkflowStep("approval", StepType.APPROVAL),
        WorkflowStep("effect", StepType.CAPABILITY, "effect"),
    )
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version)
    assert run.state is WorkflowState.WAITING_APPROVAL
    assert runtime.store.checkpoints(run.run_id)["effect"]["status"] == "completed"
    assert (
        runtime.resume(run.run_id, approved_steps=("approval",)).state
        is WorkflowState.COMPLETED
    )
    assert calls == ["one"]


def test_stale_state_writer_cannot_overwrite_cancellation(tmp_path):
    runtime = WorkflowRuntime(str(tmp_path))
    spec = definition(WorkflowStep("approval", StepType.APPROVAL))
    runtime.register(spec)
    waiting = runtime.start(spec.workflow_id, spec.version)
    runtime.cancel(waiting.run_id)
    waiting.state = WorkflowState.RUNNING
    with pytest.raises(WorkflowConflictError):
        runtime.store.save_run(waiting)
    assert runtime.store.get_run(waiting.run_id).state is WorkflowState.CANCELLED


@pytest.mark.parametrize("field", ["definition", "inputs", "checkpoint"])
def test_corrupt_binding_never_admits_dependent_effect(tmp_path, field):
    calls = []
    runtime = WorkflowRuntime(
        str(tmp_path),
        handlers={"effect": lambda step, context: calls.append("effect") or {}},
    )
    spec = definition(
        WorkflowStep("first", StepType.TRANSFORM, params={"value": "original"}),
        WorkflowStep("approval", StepType.APPROVAL, depends_on=("first",)),
        WorkflowStep("effect", StepType.CAPABILITY, "effect", depends_on=("approval",)),
    )
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version, {"source": "original"})
    if field == "checkpoint":
        checkpoint = runtime.store.checkpoints(run.run_id)["first"]
        checkpoint["output"]["value"] = "tampered"
        runtime.store.checkpoint(run.run_id, "first", checkpoint)
    else:
        with runtime.store._db() as db:
            if field == "inputs":
                value = runtime.store._run_dict(run)
                value["inputs"]["source"] = "tampered"
                db.execute(
                    "UPDATE workflow_runs SET run_json=? WHERE run_id=?",
                    (json.dumps(value), run.run_id),
                )
            else:
                value = runtime.store._definition_dict(spec)
                value["steps"][0]["params"]["value"] = "tampered"
                db.execute(
                    "UPDATE workflow_definitions SET definition_json=? WHERE workflow_id=? AND version=?",
                    (json.dumps(value), spec.workflow_id, spec.version),
                )
    assert (
        runtime.resume(run.run_id, approved_steps=("approval",)).state
        is WorkflowState.UNKNOWN
    )
    assert runtime.store.get_run(run.run_id).state is WorkflowState.UNKNOWN
    assert calls == []


@pytest.mark.parametrize(
    "corruption", ["missing", "binding_digest", "output_digest", "state_only"]
)
def test_completion_without_checkpoint_evidence_cannot_admit_dependent_effect(
    tmp_path, corruption
):
    effects = []
    runtime = WorkflowRuntime(
        str(tmp_path),
        handlers={
            "effect": lambda step, context: effects.append(context["run_id"]) or {}
        },
    )
    spec = definition(
        WorkflowStep("first", StepType.TRANSFORM, params={"value": "original"}),
        WorkflowStep("approval", StepType.APPROVAL, depends_on=("first",)),
        WorkflowStep("effect", StepType.CAPABILITY, "effect", depends_on=("approval",)),
    )
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version)
    if corruption == "missing":
        with runtime.store._db() as db:
            db.execute(
                "DELETE FROM workflow_checkpoints WHERE run_id=? AND step_id='first'",
                (run.run_id,),
            )
    elif corruption == "state_only":
        runtime.store.checkpoint(run.run_id, "first", {"status": "started"})
    else:
        checkpoint = runtime.store.checkpoints(run.run_id)["first"]
        checkpoint.pop(corruption)
        runtime.store.checkpoint(run.run_id, "first", checkpoint)
    assert (
        runtime.resume(run.run_id, approved_steps=("approval",)).state
        is WorkflowState.UNKNOWN
    )
    assert effects == []


def test_trusted_callable_policy_fallback_is_copied_and_explicit_map_wins(tmp_path):
    class Handler:
        workflow_handler_policy = WorkflowHandlerPolicy(reconcile_started=True)

        def __init__(self):
            self.calls = 0

        def __call__(self, step, context):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("journal requires reconciliation")
            return {"reconciled": True}

    handler = Handler()
    runtime = WorkflowRuntime(str(tmp_path), handlers={"effect": handler})
    handler.workflow_handler_policy = WorkflowHandlerPolicy()
    spec = definition(WorkflowStep("effect", StepType.CAPABILITY, "effect", retries=2))
    runtime.register(spec)
    run = runtime.start(spec.workflow_id, spec.version)
    assert runtime.resume(run.run_id).state is WorkflowState.COMPLETED
    assert handler.calls == 2
    second = Handler()
    blocked = WorkflowRuntime(
        str(tmp_path),
        handlers={"effect": second},
        handler_policies={"effect": WorkflowHandlerPolicy()},
    )
    run = blocked.start(spec.workflow_id, spec.version)
    assert blocked.resume(run.run_id).state is WorkflowState.UNKNOWN
    assert second.calls == 1


@pytest.mark.parametrize(
    "invalid",
    [{"reconcile_started": True}, WorkflowHandlerPolicy(reconcile_started="yes")],
)
def test_callable_policy_requires_typed_trusted_contract(tmp_path, invalid):
    def handler(step, context):
        return {}

    handler.workflow_handler_policy = invalid
    with pytest.raises(TypeError, match="trusted host"):
        WorkflowRuntime(str(tmp_path), handlers={"effect": handler})


def test_generic_capability_handler_cannot_retry_another_contract_action(tmp_path):
    calls = []
    runtime = WorkflowRuntime(
        str(tmp_path),
        handlers={"capability": lambda step, context: calls.append(step.action) or {}},
        handler_policies={
            "capability": policy(capability_id="registered.read", effect="read_only")
        },
    )
    spec = definition(
        WorkflowStep("effect", StepType.CAPABILITY, "unrelated.write", retries=3)
    )
    runtime.register(spec)
    assert runtime.start(spec.workflow_id, spec.version).state is WorkflowState.UNKNOWN
    assert calls == []

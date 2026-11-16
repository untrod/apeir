"""Recurring intent uses original Workflow runs, never timer-issued authority."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import sqlite3

import pytest
from typer.testing import CliRunner

from nous_runtime.governance.cli import _build_context
from nous_runtime.workflow.automation import AutomationConsumer
from nous_runtime.workflow.models import (
    StepType,
    TriggerType,
    WorkflowDefinition,
    WorkflowState,
    WorkflowStep,
)
from nous_runtime.workflow.runtime import WorkflowRuntime
from nous_runtime.workflow.schedule import cron_expression, latest_occurrence
from nous_runtime.workflow.store import (
    AutomationBusyError,
    WorkflowBindingError,
    binding_digest,
)
from tests.test_automation_consumer import (
    approve,
    automation_http as automation_http_fixture,
    consumer as consumer_fixture,
    human_env as human_env_fixture,
)

consumer = consumer_fixture
automation_http = automation_http_fixture
human_env = human_env_fixture
START = datetime(2026, 1, 1, 12, 0, 1, tzinfo=timezone.utc)


@pytest.fixture
def calendar(consumer):
    clock = [START]
    consumer.clock = lambda: clock[0]
    return clock


def definition(consumer, *, step=None):
    result = WorkflowDefinition(
        "cron-example",
        "1",
        TriggerType.MANUAL,
        (
            step
            or WorkflowStep("result", StepType.TRANSFORM, params={"value": "recorded"}),
        ),
        inputs_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "additionalProperties": False,
        },
    )
    WorkflowRuntime(str(consumer.root)).register(result)
    return result


def bind(consumer, *, trigger="cron", cron="* * * * *", **kwargs):
    definition(consumer)
    return consumer.add_workflow(
        name="Recurring result",
        workflow_id="cron-example",
        version="1",
        trigger=trigger,
        cron=cron,
        **kwargs,
    )


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        "",
        "@reboot",
        "* * * * * *",
        "60 * * * *",
        "* 24 * * *",
        "0 0 30 2 *",
        "* * * 13 *",
        "* * * * MON",
        "* * * * *\n",
        "0/0 * * * *",
        "*/" * 70,
        "$(touch /tmp/not-a-command)",
    ],
)
def test_calendar_rejects_unsupported_or_unbounded_input(value):
    with pytest.raises(ValueError):
        cron_expression(value)


def test_calendar_uses_utc_minutes_leap_dates_and_conventional_day_or():
    assert cron_expression(" */5  * * * * ") == "*/5 * * * *"
    assert latest_occurrence("* * * * *", START, START) is None
    minute = START.replace(minute=1, second=0)
    assert latest_occurrence("* * * * *", minute, START) == minute.isoformat(
        timespec="microseconds"
    )
    leap = datetime(2028, 2, 29, tzinfo=timezone.utc)
    assert latest_occurrence("0 0 29 2 *", leap, START) == leap.isoformat(
        timespec="microseconds"
    )
    # January 5 is Monday, even though it is not the 15th of the month.
    monday = datetime(2026, 1, 5, tzinfo=timezone.utc)
    assert latest_occurrence("0 0 15 * 1", monday, START) == monday.isoformat(
        timespec="microseconds"
    )
    with pytest.raises(ValueError, match="explicit UTC"):
        latest_occurrence("* * * * *", minute.replace(tzinfo=None), START)


def test_registered_workflow_inputs_and_original_checkpoints_survive_restart(
    consumer, calendar
):
    binding = bind(consumer, inputs={"message": "original input"})
    assert consumer.run_due() == []
    calendar[0] += timedelta(minutes=1)
    result = consumer.run_due()[0]
    assert result["state"] == "completed" and result["simulated"] is False
    assert result["works"] == [] and result["effect_counts"] == {}
    assert result["kernel_traversed"] is False
    run = consumer.store.get_run(result["run_id"])
    assert run.inputs == {"message": "original input"}
    assert run.outputs == {"result": {"value": "recorded", "inputs": run.inputs}}
    checkpoint = consumer.store.checkpoints(run.run_id)["result"]
    assert checkpoint["status"] == "completed" and checkpoint["attempts"] == 1
    restarted = AutomationConsumer(
        consumer.root, gate=consumer.gate, clock=consumer.clock
    )
    assert restarted.history(binding["id"])["history"][0]["run_id"] == run.run_id
    assert restarted.run_due() == []


def test_missed_minutes_coalesce_and_clock_rollback_cannot_replay(consumer, calendar):
    binding = bind(consumer)
    calendar[0] += timedelta(hours=3, seconds=17)
    result = consumer.run_due()[0]
    original = consumer.store.automation_history(binding["id"])[0]
    assert original["trigger_key"] == "cron:2026-01-01T15:00:00.000000+00:00"
    assert len(consumer.store.automation_history(binding["id"])) == 1
    calendar[0] -= timedelta(minutes=10)
    assert consumer.run_due() == []
    assert (
        consumer.trigger(binding["id"], original["trigger_key"])["run_id"]
        == result["run_id"]
    )
    with pytest.raises(ValueError, match="latest due"):
        consumer.trigger(binding["id"], "cron:2026-01-01T12:01:00.000000+00:00")
    calendar[0] += timedelta(minutes=11)
    assert consumer.run_due()[0]["run_id"] != result["run_id"]


def test_concurrent_ticks_share_one_atomic_original_run(consumer, calendar):
    binding = bind(consumer)
    calendar[0] += timedelta(minutes=1)
    services = [
        AutomationConsumer(consumer.root, gate=consumer.gate, clock=consumer.clock)
        for _ in range(2)
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(lambda service: service.run_due(), services))
    assert any(values)
    history = consumer.store.automation_history(binding["id"])
    assert len(history) == 1
    run_id = history[0]["run"]["run_id"]
    assert all(result["run_id"] == run_id for batch in values for result in batch)
    assert consumer.store.checkpoints(run_id)["result"]["attempts"] == 1


def test_restart_after_claim_recovers_original_pending_occurrence(
    consumer, calendar, monkeypatch
):
    binding = bind(consumer)
    calendar[0] += timedelta(minutes=1)
    with monkeypatch.context() as patch:
        patch.setattr(
            consumer,
            "_consume",
            lambda *args: (_ for _ in ()).throw(OSError("process stopped after claim")),
        )
        with pytest.raises(OSError, match="after claim"):
            consumer.run_due()
    original = consumer.store.automation_history(binding["id"])[0]["run"]
    assert original["state"] == "pending"
    calendar[0] += timedelta(minutes=3)
    restarted = AutomationConsumer(
        consumer.root, gate=consumer.gate, clock=consumer.clock
    )
    result = restarted.run_due()[0]
    assert result["run_id"] == original["run_id"] and result["state"] == "completed"
    assert len(consumer.store.automation_history(binding["id"])) == 1


@pytest.mark.parametrize(
    "retries, expected", [(0, WorkflowState.UNKNOWN), (1, WorkflowState.COMPLETED)]
)
def test_interrupted_pure_handler_resumes_original_started_checkpoint(
    consumer, calendar, monkeypatch, retries, expected
):
    definition(
        consumer,
        step=WorkflowStep(
            "result", StepType.TRANSFORM, retries=retries, params={"value": "recorded"}
        ),
    )
    binding = consumer.add_workflow(
        name="Original retry budget",
        workflow_id="cron-example",
        version="1",
        trigger="cron",
        cron="* * * * *",
    )
    calendar[0] += timedelta(minutes=1)
    with monkeypatch.context() as patch:

        def interrupted(*args):
            raise SystemExit("operator process stopped")

        patch.setattr(WorkflowRuntime, "_builtin_handler", staticmethod(interrupted))
        with pytest.raises(SystemExit, match="process stopped"):
            consumer.run_due()
    original = consumer.store.automation_history(binding["id"])[0]["run"]
    assert original["state"] == "running"
    assert (
        consumer.store.checkpoints(original["run_id"])["result"]["status"] == "started"
    )
    restarted = AutomationConsumer(
        consumer.root, gate=consumer.gate, clock=consumer.clock
    )
    assert restarted.run_due()[0]["run_id"] == original["run_id"]
    assert consumer.store.get_run(original["run_id"]).state is expected
    assert consumer.run_due() == []
    assert len(consumer.store.automation_history(binding["id"])) == 1


def test_disable_is_not_cancel_and_cancel_is_not_future_disable(consumer, calendar):
    binding = bind(consumer)
    calendar[0] += timedelta(minutes=1)
    key = "cron:2026-01-01T12:01:00.000000+00:00"
    original = consumer.store.claim_automation_run(binding["id"], key, serial=True)
    consumer.store.set_automation_enabled(binding["id"], False)
    assert consumer.run_due() == []
    assert consumer.store.get_run(original.run_id).state is WorkflowState.PENDING
    assert consumer.resume(binding["id"], original.run_id)["state"] == "completed"
    consumer.store.set_automation_enabled(binding["id"], True)
    calendar[0] += timedelta(minutes=1)
    second = consumer.store.claim_automation_run(
        binding["id"], "cron:2026-01-01T12:02:00.000000+00:00", serial=True
    )
    assert consumer.cancel(binding["id"], second.run_id)["state"] == "cancelled"
    assert consumer.resume(binding["id"], second.run_id)["state"] == "cancelled"
    calendar[0] += timedelta(minutes=1)
    assert consumer.run_due()[0]["run_id"] not in {original.run_id, second.run_id}


def test_original_failed_or_unknown_run_blocks_new_occurrences(consumer, calendar):
    binding = bind(consumer)
    calendar[0] += timedelta(minutes=1)
    original = consumer.store.claim_automation_run(
        binding["id"], "cron:2026-01-01T12:01:00.000000+00:00", serial=True
    )
    consumer.store.mark_unknown(original.run_id, "unconfirmed original result")
    calendar[0] += timedelta(minutes=1)
    assert consumer.run_due() == []
    with pytest.raises(AutomationBusyError):
        consumer.trigger(binding["id"], "cron:2026-01-01T12:02:00.000000+00:00")
    assert len(consumer.store.automation_history(binding["id"])) == 1
    assert consumer.history(binding["id"])["history"][0]["state"] == "unknown"


@pytest.mark.parametrize(
    "step_type",
    [
        StepType.AGENT,
        StepType.COMMAND,
        StepType.CAPABILITY,
        StepType.CONNECTOR,
        StepType.APPROVAL,
    ],
)
def test_unbound_effectful_or_approval_handlers_cannot_be_timer_authority(
    consumer, calendar, step_type
):
    definition(consumer, step=WorkflowStep("unsafe", step_type, action="some.action"))
    with pytest.raises(ValueError, match="qualified pure"):
        consumer.add_workflow(
            name="Cannot grant execution",
            workflow_id="cron-example",
            version="1",
            trigger="cron",
            cron="* * * * *",
        )
    assert consumer.list() == []


@pytest.mark.parametrize(
    "step",
    [
        WorkflowStep("x", StepType.TRANSFORM, approval_required=True),
        WorkflowStep("x", StepType.WAIT, compensation="write"),
        WorkflowStep("x", StepType.CONDITION, condition="expression"),
        WorkflowStep("x", StepType.TRANSFORM, action="private.handler"),
    ],
)
def test_pure_qualification_does_not_discard_execution_semantics(
    consumer, calendar, step
):
    definition(consumer, step=step)
    with pytest.raises(ValueError, match="qualified pure"):
        consumer.add_workflow(
            name="Unsupported semantics", workflow_id="cron-example", version="1"
        )


def test_schema_rejection_precedes_any_trigger_or_run(consumer, calendar):
    definition(consumer)
    for inputs in (
        {"message": 42},
        {"_approved_steps": ["mutate"]},
        [],
        {"other": "field"},
    ):
        with pytest.raises(ValueError):
            consumer.add_workflow(
                name="Bad inputs",
                workflow_id="cron-example",
                version="1",
                inputs=inputs,
            )
    assert consumer.list() == []


def test_changed_output_or_cron_policy_cannot_project_success(consumer, calendar):
    binding = bind(consumer)
    calendar[0] += timedelta(minutes=1)
    result = consumer.run_due()[0]
    with sqlite3.connect(consumer.store.path) as db:
        row = db.execute(
            "SELECT run_json FROM workflow_runs WHERE run_id=?", (result["run_id"],)
        ).fetchone()
        run = json.loads(row[0])
        run["outputs"]["result"]["value"] = "invented"
        db.execute(
            "UPDATE workflow_runs SET run_json=? WHERE run_id=?",
            (json.dumps(run), result["run_id"]),
        )
    with pytest.raises(WorkflowBindingError):
        consumer.history(binding["id"])
    # A rehashed unsupported calendar policy is still not an accepted adapter.
    with sqlite3.connect(consumer.store.path) as db:
        row = db.execute(
            "SELECT binding_json FROM workflow_automations WHERE automation_id=?",
            (binding["id"],),
        ).fetchone()
        value = json.loads(row[0])
        value["timezone"] = "local"
        db.execute(
            "UPDATE workflow_automations SET binding_json=?, binding_digest=? WHERE automation_id=?",
            (json.dumps(value), binding_digest(value), binding["id"]),
        )
    with pytest.raises(WorkflowBindingError, match="policy changed"):
        consumer.trigger(binding["id"], "cron:2026-01-01T12:01:00.000000+00:00")


def test_cron_simulation_keeps_each_new_effect_behind_original_human_approval(
    consumer, calendar
):
    binding = consumer.add_simulation(
        name="Recurring simulation", trigger="cron", cron="* * * * *"
    )
    calendar[0] += timedelta(minutes=1)
    pending = consumer.run_due()[0]
    work_id = pending["outputs"]["mutate"]["work_id"]
    assert (
        pending["state"] == "waiting_approval"
        and pending["effect_counts"][work_id] == 0
    )
    calendar[0] += timedelta(minutes=3)
    assert consumer.run_due() == []
    assert len(consumer.store.automation_history(binding["id"])) == 1
    approve(consumer, pending)
    completed = consumer.resume(binding["id"], pending["run_id"])
    assert (
        completed["state"] == "completed" and completed["effect_counts"][work_id] == 1
    )
    second = consumer.run_due()[0]
    assert (
        second["state"] == "waiting_approval" and second["run_id"] != pending["run_id"]
    )
    assert (
        second["outputs"]["mutate"]["approval_request_id"]
        != pending["outputs"]["mutate"]["approval_request_id"]
    )
    original_history = {
        entry["run_id"]: entry for entry in consumer.history(binding["id"])["history"]
    }
    assert original_history[pending["run_id"]]["effect_counts"][work_id] == 1
    assert second["effect_counts"][second["outputs"]["mutate"]["work_id"]] == 0
    assert consumer.run_due() == []
    assert consumer.run_due(include_simulation=False) == []


def test_authority_revocation_after_claim_leaves_original_pending_for_review(
    consumer, calendar
):
    binding = bind(consumer)
    calendar[0] += timedelta(minutes=1)
    checks = []

    def current_authority():
        checks.append(True)
        if len(checks) > 1:
            raise PermissionError("current authority revoked")

    consumer.before_consume = current_authority
    with pytest.raises(PermissionError, match="revoked"):
        consumer.run_due()
    original = consumer.store.automation_history(binding["id"])[0]["run"]
    assert original["state"] == "pending" and original["outputs"] == {}
    assert consumer.store.checkpoints(original["run_id"]) == {}


def test_local_cli_watch_rechecks_authority_and_stores_no_session(
    consumer, calendar, monkeypatch
):
    from nous_runtime.cli.main import app
    from nous_runtime.workflow import automation_cli

    definition(consumer)
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(consumer.root))
    monkeypatch.setattr("nous_runtime.governance.gate._gate_instance", consumer.gate)
    runner = CliRunner()
    created = runner.invoke(
        app,
        [
            "automation",
            "bind-workflow",
            "CLI timer",
            "cron-example",
            "1",
            "--due-at",
            "2026-01-01T00:00:00Z",
        ],
    )
    assert created.exit_code == 0, created.output
    automation_id = json.loads(created.output)["id"]
    calls = []

    def context():
        calls.append(True)
        return _build_context()

    monkeypatch.setattr(automation_cli, "_build_context", context)
    first = runner.invoke(app, ["automation", "watch", "--workflow", "--ticks", "1"])
    assert first.exit_code == 0, first.output
    original = json.loads(first.output)["runs"][0]
    restarted = runner.invoke(
        app, ["automation", "watch", "--workflow", "--ticks", "1"]
    )
    assert restarted.exit_code == 0 and json.loads(restarted.output)["runs"] == []
    assert len(calls) >= 2
    history = runner.invoke(app, ["automation", "history", automation_id, "--workflow"])
    assert (
        history.exit_code == 0
        and json.loads(history.output)["history"][0]["run_id"] == original["run_id"]
    )
    binding = consumer.store.get_automation(automation_id)
    assert (
        not {"context", "session", "credential", "token", "grant", "approval"}
        & binding.keys()
    )
    simulation = consumer.add_simulation(name="Explicit opt-in")
    refused = runner.invoke(
        app,
        [
            "automation",
            "trigger",
            simulation["id"],
            "--trigger-key",
            "forbidden",
            "--workflow",
        ],
    )
    assert refused.exit_code == 2
    assert consumer.store.automation_history(simulation["id"]) == []


def test_real_http_cron_creation_tick_and_reused_nonce_cannot_create_another_run(
    consumer, calendar, automation_http, monkeypatch
):
    from nous_runtime.api import desktop_routes

    real_service = desktop_routes._automation_service

    def timed_service(*args, **kwargs):
        service = real_service(*args, **kwargs)
        service.clock = consumer.clock
        return service

    monkeypatch.setattr(desktop_routes, "_automation_service", timed_service)
    definition(consumer)
    auth, context, request = automation_http
    create_path = "/api/v1/automations/add"
    body = {
        "adapter": "workflow",
        "name": "HTTP Cron",
        "workflow_id": "cron-example",
        "version": "1",
        "inputs": {"message": "original"},
        "trigger": "cron",
        "cron": "* * * * *",
    }
    created = request(
        body, auth.nonce(context, "POST", create_path, body)["nonce"], create_path
    )
    assert created["ok"], created
    automation_id = created["data"]["id"]
    calendar[0] += timedelta(minutes=1)
    # Only the clock is controlled. HTTP, human authentication, nonce admission,
    # original Workflow execution and persistence all use their real owners.
    tick = {"action": "tick", "automation_id": automation_id}
    path = "/api/v1/automations/action"
    nonce = auth.nonce(context, "POST", path, tick)["nonce"]
    missing_nonce = request(tick, "")
    assert missing_nonce["ok"] is False
    assert consumer.store.automation_history(automation_id) == []
    consumed = request(tick, nonce)
    assert consumed["ok"], consumed
    run = consumed["data"]["runs"][0]
    assert run["state"] == "completed" and run["simulated"] is False
    assert run["qualification"] == "PURE_WORKFLOW"
    assert request(tick, nonce)["ok"] is False
    assert len(consumer.store.automation_history(automation_id)) == 1
    # Presentation/authority and backfill options never enter a schedule.
    unsafe = {
        **body,
        "approval_required": False,
        "timezone": "local",
        "grant": "invented",
    }
    refused = request(
        unsafe, auth.nonce(context, "POST", create_path, unsafe)["nonce"], create_path
    )
    assert refused["ok"] is False
    assert len(consumer.list()) == 1


def test_store_enforces_cron_overlap_even_without_caller_serial_flag(
    consumer, calendar
):
    binding = bind(consumer)
    original = consumer.store.claim_automation_run(
        binding["id"], "cron:2026-01-01T12:01:00.000000+00:00"
    )
    with pytest.raises(AutomationBusyError):
        consumer.store.claim_automation_run(
            binding["id"], "cron:2026-01-01T12:02:00.000000+00:00"
        )
    assert (
        consumer.store.automation_run(binding["id"], original.run_id).run_id
        == original.run_id
    )


def test_condition_skip_preserves_original_execution_semantics(consumer, calendar):
    definition(
        consumer,
        step=WorkflowStep(
            "result", StepType.CONDITION, params={"input": "message", "equals": "match"}
        ),
    )
    binding = consumer.add_workflow(
        name="Condition",
        workflow_id="cron-example",
        version="1",
        inputs={"message": "different"},
        trigger="cron",
        cron="* * * * *",
    )
    calendar[0] += timedelta(minutes=1)
    result = consumer.run_due()[0]
    assert result["state"] == "completed" and result["step_states"] == {
        "result": "skipped"
    }
    assert result["outputs"] == {}
    assert consumer.history(binding["id"])["history"][0]["run_id"] == result["run_id"]


def test_actual_http_delivers_host_challenge_url_without_disabling_generic_redaction(
    consumer, automation_http
):
    import base64
    import hashlib
    from nous_runtime.api.responses import ok_response
    from nous_runtime.control_plane.operations import (
        HumanChallengeResponse,
        human_challenge_route,
    )
    from urllib.parse import urlsplit, parse_qs

    _, _, request = automation_http
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(b"fake-automation-pkce" * 5).digest())
        .decode()
        .rstrip("=")
    )
    malicious = "https://attacker.example.invalid/"
    body = {"code_challenge": challenge, "authorization_url": malicious}
    ordinary = human_challenge_route(body)
    assert isinstance(ordinary, HumanChallengeResponse)
    assert "authorization_url" not in ordinary["data"]
    assert ordinary.authorization_url not in json.dumps(ordinary)
    assert (
        ok_response({"authorization_url": ordinary.authorization_url})["data"][
            "authorization_url"
        ]
        == "<REDACTED>"
    )
    wire = request(body, "", "/api/v1/control/human/challenge")
    assert wire["ok"], wire
    target = urlsplit(wire["data"]["authorization_url"])
    assert target.hostname == "identity.example.test" and target.scheme == "https"
    params = parse_qs(target.query)
    assert params["state"] == [wire["data"]["challenge_id"]]
    assert params["code_challenge"] == [challenge]
    assert params["code_challenge_method"] == ["S256"]
    assert malicious not in json.dumps(wire)
    audit = json.dumps(consumer.gate.store.operation_audit())
    assert (
        wire["data"]["authorization_url"] not in audit
        and params["nonce"][0] not in audit
    )


def test_tick_keeps_one_clock_snapshot_when_dispatch_crosses_a_minute(
    consumer, calendar
):
    binding = bind(consumer)
    first = START + timedelta(minutes=1)
    times = iter([first, first + timedelta(minutes=1)] * 10)
    consumer.clock = lambda: next(times)
    result = consumer.run_due()[0]
    history = consumer.store.automation_history(binding["id"])
    assert len(history) == 1 and history[0]["run"]["run_id"] == result["run_id"]
    assert history[0]["trigger_key"] == "cron:2026-01-01T12:01:00.000000+00:00"


def test_later_concurrent_occurrence_does_not_crash_an_older_tick(
    consumer, calendar, monkeypatch
):
    binding = bind(consumer)
    calendar[0] = START + timedelta(minutes=1)
    other = AutomationConsumer(
        consumer.root, gate=consumer.gate, clock=lambda: START + timedelta(minutes=2)
    )
    claim = consumer.store.claim_automation_run

    def later_wins(*args, **kwargs):
        other.run_due()
        return claim(*args, **kwargs)

    monkeypatch.setattr(consumer.store, "claim_automation_run", later_wins)
    assert consumer.run_due() == []
    history = other.store.automation_history(binding["id"])
    assert (
        len(history) == 1
        and history[0]["trigger_key"] == "cron:2026-01-01T12:02:00.000000+00:00"
    )

"""Persisted reports must not substitute for the current authenticated session."""

import asyncio
import contextlib

import pytest

from nous_runtime.node_runtime.relay import NodeRelayClient
from nous_runtime.reality.preview import _DemoComponents
from tests.reality import test_simulated_execution as simulation_contracts
from tests.reality.test_simulated_execution import Simulation
from nous_runtime.agent import AgentSessionState
from nous_runtime.governance.cli import _build_context
from nous_runtime.node_runtime.distributed_work import DistributedWorkState
from nous_runtime.node_runtime.service import WorkloadResponseLost
from tests.reality.test_simulated_execution import (
    STABLE,
    WORK_ID,
    SimulationFault,
    request_firmware,
    resume_after_terminal_observation_delivery,
    resume_firmware,
    simulation,
    wait_for,
)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("factory", [Simulation, _DemoComponents])
def test_restart_waits_for_current_signed_resource_report(
    tmp_path, monkeypatch, factory
):
    async def scenario():
        first = factory(tmp_path)
        try:
            await first.start()
            node_id = first.node.identity.node_id
            previous = first.server.reports[node_id]["signed_envelopes"][
                "RESOURCE_REPORT"
            ]["message_id"]
        finally:
            await first.close()

        entered, release = asyncio.Event(), asyncio.Event()
        original_send = NodeRelayClient._send

        async def hold_registration(self, websocket, message_type, *args, **kwargs):
            if message_type == "REGISTER":
                entered.set()
                await release.wait()
            return await original_send(self, websocket, message_type, *args, **kwargs)

        monkeypatch.setattr(NodeRelayClient, "_send", hold_registration)
        restored = factory(tmp_path)
        assert (
            restored.server.reports[node_id]["signed_envelopes"]["RESOURCE_REPORT"][
                "message_id"
            ]
            == previous
        )
        startup = asyncio.create_task(restored.start())
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            # The persisted report is valid historical evidence, but this Node
            # has not even sent REGISTER on its new connection yet.
            assert node_id not in restored.server.connections
            assert not startup.done(), "Historical report falsely completed startup"
            release.set()
            await asyncio.wait_for(startup, timeout=15)
            assert node_id in restored.server.connections
            fresh = restored.server.reports[node_id]["signed_envelopes"][
                "RESOURCE_REPORT"
            ]["message_id"]
            assert fresh != previous
            assert restored.provider.execution_count("work-simulated-effect") == 0
            assert restored.provider.execution_count("preview-firmware-update") == 0
        finally:
            release.set()
            await startup
            await restored.close()

    asyncio.run(scenario())


def test_revoked_effect_recovery_survives_slow_authenticated_restart(
    tmp_path, monkeypatch
):
    registrations = 0
    original_send = NodeRelayClient._send

    async def delay_restart(self, websocket, message_type, *args, **kwargs):
        nonlocal registrations
        if message_type == "REGISTER":
            registrations += 1
            if registrations == 2:
                # Longer than the existing three-second Work wait, but within
                # the unchanged fifteen-second connection-readiness budget.
                await asyncio.sleep(4)
        return await original_send(self, websocket, message_type, *args, **kwargs)

    monkeypatch.setattr(NodeRelayClient, "_send", delay_restart)
    simulation_contracts.test_approved_firmware_lost_response_recovers_after_grant_revocation_without_replay(
        tmp_path
    )
    assert registrations == 2


async def _await_original_observation_hold(entered, resumption):
    """Follow the owned producer, not a second deadline covering its preparation."""
    reached = asyncio.create_task(entered.wait())
    try:
        await asyncio.wait({reached, resumption}, return_when=asyncio.FIRST_COMPLETED)
        if not entered.is_set():
            # Surface its original failure/cancellation. A successful return
            # before the fault was injected is also an invalid acceptance run.
            result = await resumption
            pytest.fail(
                "Original resumption finished without the observation hold: "
                f"state={result.state}, error={result.error}"
            )
    finally:
        reached.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reached


@pytest.mark.parametrize(
    "deliver_result,held_reads",
    [(True, 1), (False, 1), (True, 2)],
    ids=["delayed", "missing", "delayed-again"],
)
def test_delayed_observation_after_restart_requires_original_read_evidence(
    tmp_path, monkeypatch, deliver_result, held_reads
):
    async def scenario():
        async with simulation(tmp_path, single_connection=True) as first:
            paused = await request_firmware(first, wait_timeout=3)
            first.provider.inject_fault(
                STABLE, SimulationFault.EFFECT_THEN_RESPONSE_LOST
            )
            first.handler.approvals.approve_operation_once(
                paused.pending_approvals[0], _build_context(), gate=first.governance
            )
            waiting = await resume_firmware(first, paused.session_id)
            await wait_for(first.client_task.done)
            assert waiting.state is AgentSessionState.WAITING
            assert isinstance(first.client_task.exception(), WorkloadResponseLost)
            assert first.provider.execution_count(WORK_ID) == 1
            auth_id = first.work().execution_arguments["authorization_id"]
            with first.governance.store.operation_transaction() as db:
                grant_id = db.execute(
                    "SELECT lease_id FROM governance_leases WHERE proposal_hash=?",
                    (auth_id,),
                ).fetchone()[0]
            first.governance.revoke_operation_authority(
                auth_id, _build_context(), grant_id=grant_id
            )

        entered, release = asyncio.Event(), asyncio.Event()
        original_send = NodeRelayClient._send
        held = {}
        second_held = {}
        second_entered, second_release = asyncio.Event(), asyncio.Event()

        async def hold_observation(self, websocket, message_type, payload, **kwargs):
            if (
                message_type == "WORKLOAD_STATUS"
                and str(payload.get("workload_id", "")).startswith("observe_")
                and not held
            ):
                held.update(payload)
                entered.set()
                await release.wait()
            elif (
                held_reads == 2
                and message_type == "WORKLOAD_STATUS"
                and str(payload.get("workload_id", "")).startswith("observe_")
                and payload["workload_id"] != held.get("workload_id")
                and not second_held
            ):
                second_held.update(payload)
                second_entered.set()
                await second_release.wait()
            return await original_send(self, websocket, message_type, payload, **kwargs)

        monkeypatch.setattr(NodeRelayClient, "_send", hold_observation)
        async with simulation(tmp_path) as restored:
            resumption = asyncio.create_task(
                resume_after_terminal_observation_delivery(restored, paused.session_id)
            )
            try:
                await _await_original_observation_hold(entered, resumption)
                acquisition_id = held["workload_id"]

                def waiting_on_original_read():
                    current = restored.coordinator.require(paused.session_id)
                    return (
                        current.state is AgentSessionState.WAITING
                        and current.error
                        == f"distributed Workflow Work timed out: {acquisition_id}"
                    )

                await wait_for(waiting_on_original_read)
                result = restored.coordinator.require(paused.session_id)
                assert result.state is AgentSessionState.WAITING
                assert not resumption.done()
                assert result.error == (
                    f"distributed Workflow Work timed out: {acquisition_id}"
                )
                assert result.workflow_run_id == paused.workflow_run_id
                assert restored.work().state is DistributedWorkState.VERIFIED
                assert not restored.work().effect_verification
                assert restored.provider.execution_count(WORK_ID) == 1
                assert acquisition_id not in restored.server.results
                # A journaled read and fresh resource report still do not prove
                # that its signed result reached the Controller.
                assert held["state"] == "COMPLETED"
                if not deliver_result:
                    # Stop the test's observation waiter, not a Node effect or
                    # Workflow. With no Controller receipt it cannot continue.
                    resumption.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await resumption
                    assert restored.coordinator.require(paused.session_id).state is (
                        AgentSessionState.WAITING
                    )
                    assert restored.work().state is DistributedWorkState.VERIFIED
                    assert not restored.work().effect_verification
                    assert restored.provider.execution_count(WORK_ID) == 1
                    return
                release.set()
                if held_reads == 2:
                    await _await_original_observation_hold(second_entered, resumption)
                    second_id = second_held["workload_id"]
                    await wait_for(
                        lambda: (
                            restored.coordinator.require(paused.session_id).error
                            == f"distributed Workflow Work timed out: {second_id}"
                        )
                    )
                    assert restored.work().state is DistributedWorkState.VERIFIED
                    assert not restored.work().effect_verification
                    assert second_id not in restored.server.results
                    assert restored.provider.execution_count(WORK_ID) == 1
                    second_release.set()
                result = await resumption
                assert result.state is AgentSessionState.COMPLETED
                assert result.workflow_run_id == paused.workflow_run_id
                assert restored.work().state is DistributedWorkState.COMMITTED
                assert restored.work().effect_verification["verdict"] == "MATCH"
                assert restored.provider.execution_count(WORK_ID) == 1
                observation_ids = restored.work().effect_verification["observation_ids"]
                # The existing finalizer acquires a fresh independent read on
                # continuation. It does not replay the revoked mutation.
                assert held["output"]["observation_id"] not in observation_ids
                if second_held:
                    assert (
                        second_held["output"]["observation_id"] not in observation_ids
                    )
            finally:
                release.set()
                second_release.set()
                with contextlib.suppress(asyncio.CancelledError):
                    await resumption

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["error", "cancelled", "no-hold"])
def test_observation_hold_propagates_producer_failure(outcome):
    async def scenario():
        entered = asyncio.Event()

        async def producer():
            if outcome == "error":
                raise RuntimeError("original read producer failed")
            if outcome == "cancelled":
                raise asyncio.CancelledError
            from types import SimpleNamespace

            return SimpleNamespace(state="WAITING", error="original read unavailable")

        task = asyncio.create_task(producer())
        expected = {
            "error": (RuntimeError, "original read producer failed"),
            "cancelled": (asyncio.CancelledError, None),
            "no-hold": (pytest.fail.Exception, "finished without the observation hold"),
        }[outcome]
        with pytest.raises(expected[0], match=expected[1]):
            await _await_original_observation_hold(entered, task)
        assert task.done()
        assert not entered.is_set()
        assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    asyncio.run(scenario())

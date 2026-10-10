"""Persisted reports must not substitute for the current authenticated session."""

import asyncio

import pytest

from nous_runtime.node_runtime.relay import NodeRelayClient
from nous_runtime.reality.preview import _DemoComponents
from tests.reality import test_simulated_execution as simulation_contracts
from tests.reality.test_simulated_execution import Simulation

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

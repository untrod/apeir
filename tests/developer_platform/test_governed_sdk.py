"""Exercise public SDK evidence conformance after existing governed Node execution."""

import asyncio
from pathlib import Path
from dataclasses import replace

from tests.reality.test_simulated_execution import simulation


def test_public_sdk_accepts_governed_effect_and_rejects_tampered_evidence(
    tmp_path, monkeypatch
):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "sdk/provider/python")
    )
    from nous_provider.runtime import (
        ContentAddressedArtifactStore,
        EffectVerifier,
        Operation,
        Observation,
    )
    from nous_provider.conformance import (
        CTKRunner,
        RuntimeConformanceTarget,
        register_runtime_suites,
    )

    async def run():
        async with simulation(tmp_path) as sim:
            await sim.execute()
            work = sim.work()
            operation = Operation(**work.execution_arguments["operation"])
            receipt = work.result_summary["remote_execution_receipt"]
            observations = tuple(
                Observation(**result["output"])
                for result in sim.controller().results.values()
                if isinstance(result.get("output"), dict)
                and result["output"].get("observation_id")
            )
            verification = EffectVerifier().verify(operation, receipt, observations)
            assert verification.committable
            target = RuntimeConformanceTarget(
                work=work,
                operation=operation,
                receipt=receipt,
                verification=verification,
                observations=observations,
                artifact_store=ContentAddressedArtifactStore(
                    sim.controller_state / "artifacts"
                ),
                artifact_digest="sha256:"
                + work.evidence_refs[0].removeprefix("artifact://sha256/"),
            )
            runner = CTKRunner()
            register_runtime_suites(runner, target)
            assert runner.run_suite("runtime-execution").certified
            assert runner.run_suite("runtime-evidence").certified
            assert sim.provider.execution_count(work.work_id) == 1
            register_runtime_suites(runner, replace(target, observations=()))
            assert not runner.run_suite("runtime-execution").certified
            register_runtime_suites(
                runner,
                replace(target, receipt={**receipt, "operation_id": "wrong-operation"}),
            )
            assert not runner.run_suite("runtime-execution").certified
            assert sim.provider.execution_count(work.work_id) == 1

    asyncio.run(run())

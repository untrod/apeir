"""Trusted local SDK host; Provider logic stays separate from authority."""

from __future__ import annotations

import asyncio
import argparse
import json
from pathlib import Path
import tempfile

from nous_provider.conformance import (
    CTKRunner,
    RuntimeConformanceTarget,
    register_runtime_suites,
)
from nous_provider.runtime import (
    CapabilityContract,
    ContentAddressedArtifactStore,
    DistributedWorkflowAdapter,
    ExecutionAuthorizationGate,
    GovernanceDecision,
    GovernanceRequest,
    GovernanceStore,
    Idempotency,
    NodeRelayClient,
    NodeRelayServer,
    NodeRuntimeConfig,
    NodeRuntimeService,
    Policy,
    ProviderRegistry,
    VerificationMethod,
    WorkflowStep,
    StepType,
)
from hello_provider import HelloProvider


class _AuthorizedHello:
    """Node adapter owned by the host; untrusted Provider receives only input."""

    def __init__(self, registry, gate, node_artifacts, request, provider=None):
        self.registry, self.gate, self.artifacts, self.request = (
            registry,
            gate,
            node_artifacts,
            request,
        )
        self.provider = provider

    def execute_bound(self, arguments, *, workload_id, node_id, binding):
        request = self.request
        if (
            workload_id != request.work_id
            or node_id != request.node_id
            or arguments != {"authorization_id": request.authorization_id}
            or binding.get("target_ref")
            != f"node://{node_id}/capability/{request.capability_id}"
        ):
            raise PermissionError("Operation binding mismatch")
        with self.gate.admit_operation(
            request.authorization_id,
            resource_check=lambda: (
                self.registry.get(self.provider.provider_id) is self.provider
            ),
        ) as revalidate:
            digest = "sha256:" + request.input_artifacts[0].removeprefix(
                "artifact://sha256/"
            )
            params = json.loads(
                ContentAddressedArtifactStore(self.artifacts.root)
                .resolve(digest)
                .read_text(encoding="utf-8")
            )
            revalidate()
            result = self.provider.invoke(request.capability_id, **params)
            if not result.get("ok"):
                raise ValueError(result.get("error", "Provider failed"))
            return result


async def run(root: Path) -> dict:
    provider, registry = HelloProvider(), ProviderRegistry()
    provider_id = registry.install(provider)
    server = None
    client_task = None
    stop = asyncio.Event()
    try:
        gate = ExecutionAuthorizationGate(
            GovernanceStore(root / ".nous"),
            operation_policy=Policy(
                policy_id="hello-read-only",
                capability_id="example.greet",
                scope="policy_controlled",
                auto_approve_read_only=True,
            ),
        )
        gate.operation_contracts.register(
            CapabilityContract(
                capability_id="example.greet",
                risk_level="LOW",
                side_effect_class="read_only",
                idempotency=Idempotency.IDEMPOTENT,
                verification_method=VerificationMethod.NONE,
            )
        ).unwrap()
        controller_state = root / ".nous" / "relay"
        cas = ContentAddressedArtifactStore(controller_state / "artifacts")
        digest = cas.store_bytes(
            b'{"name":"Developer"}',
            artifact_type="dataset",
            name="greeting-input.json",
            produced_by="hello-sdk-host",
        )["artifact"]["digest"]
        ref = "artifact://sha256/" + digest.removeprefix("sha256:")
        node_artifacts = ContentAddressedArtifactStore(
            root / ".nous" / "node" / "artifacts"
        )
        host = _AuthorizedHello(registry, gate, node_artifacts, None, provider)
        node = NodeRuntimeService(
            NodeRuntimeConfig(root / ".nous" / "node"),
            capability_handlers={"example.greet": host},
        )
        request = GovernanceRequest(
            operation_id="hello-read-work",
            work_id="hello-read-work",
            capability_id="example.greet",
            resource_id=node.identity.node_id,
            subject_id="hello-sdk-user",
            node_id=node.identity.node_id,
            workflow_run_id="hello-sdk-run",
            input_artifacts=(ref,),
            capability_inputs=gate.capability_inputs("example.greet"),
        )
        gate.register_operation(request)
        host.request = request
        server = NodeRelayServer(state_dir=controller_state, artifact_store=cas)
        server.register_node(node.identity.node_id, node.identity.public_key)
        url = await server.start()
        client_task = asyncio.create_task(
            NodeRelayClient(node, url, server.public_key).run_forever(stop)
        )
        deadline = asyncio.get_running_loop().time() + 15
        while "RESOURCE_REPORT" not in server.reports.get(node.identity.node_id, {}):
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("Node did not report")
            await asyncio.sleep(0.02)

        def admit(work):
            if (
                work.work_id != request.work_id
                or work.execution_capability != request.capability_id
                or work.input_artifacts != request.input_artifacts
                or work.target_resource_id
                or work.execution_arguments
                != {"authorization_id": request.authorization_id}
                or gate.evaluate_operation(request.authorization_id)
                is not GovernanceDecision.ALLOW
            ):
                raise PermissionError("Host policy denied Work")

        adapter = DistributedWorkflowAdapter(controller_state, work_admitter=admit)
        step = WorkflowStep(
            step_id="greet",
            step_type=StepType.CAPABILITY,
            action="distributed",
            params={
                "work_id": request.work_id,
                "capability": request.capability_id,
                "arguments": {"authorization_id": request.authorization_id},
                "input_artifacts": [ref],
                "requirements": {"node_ids": [node.identity.node_id]},
                "wait_timeout_seconds": 15,
            },
        )
        await asyncio.to_thread(adapter, step, {"run_id": "hello-sdk-run"})
        work = server.work_store.get(request.work_id)
        runner = CTKRunner()
        register_runtime_suites(
            runner, RuntimeConformanceTarget(provider=provider, work=work)
        )
        conformance = json.loads(
            runner.report_json(
                runner.run_required(["runtime-provider", "runtime-work"])
            )
        )
        unknown = GovernanceRequest(
            operation_id="unknown-work",
            work_id="unknown-work",
            capability_id="example.write",
            resource_id=provider_id,
            subject_id="hello-sdk-user",
        )
        gate.register_operation(unknown)
        denied = gate.evaluate_operation(unknown.authorization_id)
        gate.operation_contracts.register(
            CapabilityContract(
                capability_id="example.protected.read",
                risk_level="LOW",
                side_effect_class="read_only",
                idempotency=Idempotency.IDEMPOTENT,
                required_permissions=["example.read"],
            )
        ).unwrap()
        protected = GovernanceRequest(
            operation_id="protected-work",
            work_id="protected-work",
            capability_id="example.protected.read",
            resource_id=provider_id,
            subject_id="hello-sdk-user",
            capability_inputs=gate.capability_inputs("example.protected.read"),
        )
        gate.register_operation(protected)
        missing_permission = gate.evaluate_operation(protected.authorization_id)
        mutation = GovernanceRequest(
            operation_id="mutation-work",
            work_id="mutation-work",
            capability_id="device.firmware.update",
            resource_id=provider_id,
            subject_id="hello-sdk-user",
            expected_effect={"firmware_version": "2.0.0"},
            capability_inputs=gate.capability_inputs("device.firmware.update"),
        )
        gate.register_operation(mutation)
        mutation_decision = gate.evaluate_operation(mutation.authorization_id)
        registry.remove(provider_id)
        try:
            with gate.admit_operation(
                request.authorization_id,
                resource_check=lambda: registry.get(provider_id) is not None,
            ):
                raise AssertionError("Removed Provider was admitted")
        except PermissionError:
            removed_denied = True
        return {
            "workspace": str(root),
            "execution_scope": "runtime-service",
            "kernel_traversed": False,
            "work": work.to_dict(),
            "output": server.results[request.work_id]["output"],
            "unknown_capability_decision": denied.value,
            "removed_provider_denied": removed_denied,
            "missing_permission_decision": missing_permission.value,
            "mutation_decision": mutation_decision.value,
            "conformance": conformance,
            "provider_error": provider.invoke("example.write"),
            "audit": gate.store.operation_audit(),
        }
    finally:
        registry.remove(provider_id)
        stop.set()
        try:
            if client_task is not None:
                client_task.cancel()
                try:
                    await client_task
                except asyncio.CancelledError:
                    pass
        finally:
            if server is not None:
                await server.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    root = args.workspace or Path(tempfile.mkdtemp(prefix="apeir-hello-sdk-"))
    if root.exists() and any(root.iterdir()):
        parser.error("Use an empty dedicated workspace; preserve prior evidence")
    root.mkdir(parents=True, exist_ok=True)
    print(json.dumps(asyncio.run(run(root.resolve())), indent=2))


if __name__ == "__main__":
    main()

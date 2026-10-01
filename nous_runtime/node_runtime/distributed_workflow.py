"""Thin Workflow handler for the durable Distributed Work execution path."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from nous_runtime.artifact.content_store import ContentAddressedArtifactStore
from nous_runtime.workflow.models import WorkflowStep

from .distributed_work import (
    DistributedWork,
    DistributedWorkError,
    DistributedWorkState,
    WorkExecutionPolicy,
    WorkRequirements,
)
from .relay import NodeRelayServer


class DistributedWorkflowAdapter:
    """Map one existing Workflow step to one durable Compute Mesh Work."""

    def __init__(
        self,
        state_dir: str | Path,
        *,
        poll_interval_seconds: float = 0.05,
    ):
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.poll_interval_seconds = max(0.01, poll_interval_seconds)

    def __call__(self, step: WorkflowStep, context: dict[str, Any]) -> dict[str, Any]:
        params = dict(step.params)
        capability = str(params.get("capability") or step.action).strip().lower()
        if not capability:
            raise DistributedWorkError(
                "distributed Workflow step requires a capability"
            )
        work_id = str(params.get("work_id") or self._work_id(step, context))
        input_artifacts = self._input_artifacts(params, context)
        requirements_value = params.get("requirements") or {}
        if not isinstance(requirements_value, dict):
            raise DistributedWorkError("distributed Workflow requirements are invalid")
        required_capabilities = tuple(
            dict.fromkeys(
                (
                    *(
                        str(item)
                        for item in requirements_value.get("capabilities") or ()
                    ),
                    capability,
                )
            )
        )
        controller = self._controller()
        assert controller.work_store is not None
        work = controller.work_store.get(work_id)
        if work is None:
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                raise DistributedWorkError(
                    "distributed Workflow arguments must be an object"
                )
            work = controller.work_store.create(
                DistributedWork(
                    work_id=work_id,
                    intent=str(params.get("intent") or f"Workflow step {step.step_id}"),
                    creator=f"workflow:{context['run_id']}",
                    requirements=WorkRequirements(
                        architectures=tuple(
                            str(item)
                            for item in requirements_value.get("architectures") or ()
                        ),
                        operating_systems=tuple(
                            str(item)
                            for item in requirements_value.get("operating_systems")
                            or ()
                        ),
                        capabilities=required_capabilities,
                        minimum_memory_bytes=int(
                            requirements_value.get("minimum_memory_bytes") or 0
                        ),
                        gpu_required=bool(
                            requirements_value.get("gpu_required", False)
                        ),
                    ),
                    input_artifacts=input_artifacts,
                    execution_policy=WorkExecutionPolicy(
                        delivery="at_most_once", require_receipt=True
                    ),
                    execution_capability=capability,
                    execution_arguments=dict(arguments),
                )
            )
        if work.state in {
            DistributedWorkState.CREATED,
            DistributedWorkState.SCHEDULED,
        }:
            scheduled = controller.schedule_work(work_id)
            work = controller.work_store.get(work_id)
            if not scheduled["placement"]["selected_node"] or work is None:
                raise DistributedWorkError(
                    f"distributed Workflow step has no eligible Node: {step.step_id}"
                )
        if work.state is DistributedWorkState.ASSIGNED:
            controller.stage_work_dispatch(work_id)

        wait_timeout = float(params.get("wait_timeout_seconds") or 30.0)
        deadline = time.monotonic() + max(0.01, wait_timeout)
        while time.monotonic() < deadline:
            controller = self._controller()
            assert controller.work_store is not None
            work = controller.work_store.get(work_id)
            if work is None:
                raise DistributedWorkError("distributed Workflow Work disappeared")
            if work.state is DistributedWorkState.COMMITTED:
                return self._output(work.to_dict())
            if work_id in controller.results:
                reconciled = controller.reconcile_work(work_id)
                work_value = reconciled["work"]
                if work_value["state"] == DistributedWorkState.COMMITTED.value:
                    return self._output(work_value)
                raise DistributedWorkError(
                    f"distributed Workflow Work did not verify: {work_value['state']}"
                )
            time.sleep(self.poll_interval_seconds)
        raise TimeoutError(f"distributed Workflow Work timed out: {work_id}")

    def _controller(self) -> NodeRelayServer:
        return NodeRelayServer(
            state_dir=self.state_dir,
            artifact_store=ContentAddressedArtifactStore(self.state_dir / "artifacts"),
        )

    @staticmethod
    def _work_id(step: WorkflowStep, context: dict[str, Any]) -> str:
        value = f"{context['run_id']}:{step.step_id}".encode()
        return "work_" + hashlib.sha256(value).hexdigest()[:32]

    @staticmethod
    def _input_artifacts(
        params: dict[str, Any], context: dict[str, Any]
    ) -> tuple[str, ...]:
        values = [str(item) for item in params.get("input_artifacts") or ()]
        outputs = context.get("outputs") or {}
        for step_id in params.get("input_from_steps") or ():
            step_output = outputs.get(str(step_id)) or {}
            if not isinstance(step_output, dict):
                continue
            values.extend(
                str(item) for item in step_output.get("output_artifacts") or ()
            )
        return tuple(dict.fromkeys(values))

    @staticmethod
    def _output(work: dict[str, Any]) -> dict[str, Any]:
        return {
            "work_id": work["work_id"],
            "state": work["state"],
            "node_id": work["assigned_node"],
            "output_artifacts": list(work["output_artifacts"]),
            "evidence_refs": list(work["evidence_refs"]),
            "verification": dict(work["result_summary"]),
        }


__all__ = ["DistributedWorkflowAdapter"]

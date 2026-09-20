from nous_runtime.model_runtime.center import ModelCenterService
from nous_runtime.model_runtime.models import (
    ModelDescriptor,
    ModelEndpointType,
)


def service(tmp_path):
    value = ModelCenterService(tmp_path)
    value.registry.register(
        ModelDescriptor(
            model_id="local-model",
            display_name="Local Model",
            provider_id="local",
            endpoint_type=ModelEndpointType.LOCAL_SERVICE,
            capabilities=frozenset({"reasoning", "coding"}),
        )
    )
    return value


def test_model_center_lifecycle_and_snapshot(tmp_path):
    center = service(tmp_path)
    center.enable("local-model")
    snapshot = center.snapshot()
    assert snapshot["summary"]["enabled"] == 1
    assert snapshot["models"][0]["capability_scores"]["coding"] == 7
    assert center.verify("local-model")["ok"] is True
    assert center.disable("local-model")["state"] == "disabled"
    removed = center.remove("local-model")
    assert removed["state"] == "removed"
    assert removed["files_preserved"] is True


def test_model_center_repair_rejects_missing_location(tmp_path):
    center = service(tmp_path)
    center.registry.enable("local-model")
    assert center.verify("local-model")["ok"] is True

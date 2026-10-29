"""Local and cloud registrations retain distinct identities and privacy routes."""

import asyncio

import pytest

from nous_runtime.model_runtime.factory import build_gateway_from_providers
from nous_runtime.model_runtime.models import ModelRequest, PrivacyClass, RoutingMode
from nous_runtime.model_runtime.errors import ModelRoutingError


class Provider:
    def __init__(self, identity, endpoint, model="vendor/model"):
        self.provider_id = identity
        self.provider_name = identity
        self.endpoint = endpoint
        self.model = model
        self.calls = []

    def list_capabilities(self):
        return ["model.reason"]

    def invoke(self, capability_id, **params):
        self.calls.append((capability_id, params["model"]))
        return {"ok": True, "content": self.provider_id, "model": params["model"]}


def test_same_vendor_model_can_coexist_on_local_and_cloud_backends():
    gateway = build_gateway_from_providers(
        [
            Provider("cloud", "https://provider.example.test/v1"),
            Provider("workstation", "http://127.0.0.1:11434/v1"),
        ],
        allow_direct=True,
    )
    records = {
        row.descriptor.model_id: row.descriptor for row in gateway.registry.list()
    }
    assert set(records) == {"cloud/vendor/model", "workstation/vendor/model"}
    for identity, descriptor in records.items():
        assert descriptor.metadata["provider_model"] == "vendor/model"
        route = gateway.router.route(
            ModelRequest(
                task_id="selection",
                preferred_models=(identity,),
                routing_mode=RoutingMode.LOCKED,
                quality_target=0,
            )
        )
        assert route.selected_model_id == identity
        assert records[identity].provider_id == identity.split("/", 1)[0]
    route = gateway.router.route(
        ModelRequest(
            task_id="private-selection",
            privacy_policy=PrivacyClass.PRIVATE,
            quality_target=0,
        )
    )
    assert route.selected_model_id == "workstation/vendor/model"
    assert "cloud/vendor/model" not in route.fallback_model_ids


def test_locked_cloud_and_local_calls_reach_the_selected_original_provider():
    providers = [
        Provider("cloud", "https://provider.example.test/v1"),
        Provider("workstation", "http://127.0.0.1:11434/v1"),
    ]
    gateway = build_gateway_from_providers(providers, allow_direct=True)

    async def exercise():
        for provider in providers:
            identity = provider.provider_id + "/vendor/model"
            response = await gateway.invoke(
                ModelRequest(
                    task_id="fake-coexistence-" + provider.provider_id,
                    preferred_models=(identity,),
                    routing_mode=RoutingMode.LOCKED,
                    quality_target=0,
                    required_capabilities=frozenset({"reasoning"}),
                )
            )
            assert response.model_id == identity
            assert response.content == provider.provider_id

    asyncio.run(exercise())
    assert all(
        provider.calls == [("model.reason", "vendor/model")] for provider in providers
    )


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://provider.example.test/local/ollama",
        "https://localhost.example.test/v1",
        "https://127.0.0.1.example.test/v1",
        "not-an-endpoint",
    ],
)
def test_provider_label_or_url_substring_does_not_establish_locality(endpoint):
    gateway = build_gateway_from_providers(
        [
            Provider("local-ollama", endpoint),
        ],
        allow_direct=True,
    )
    with pytest.raises(ModelRoutingError):
        gateway.router.route(
            ModelRequest(
                task_id="private-selection",
                privacy_policy=PrivacyClass.PRIVATE,
                quality_target=0,
            )
        )


@pytest.mark.parametrize("host", ["localhost", "localhost.", "127.0.0.1", "[::1]"])
def test_exact_loopback_endpoints_are_local(host):
    gateway = build_gateway_from_providers(
        [
            Provider("workstation", f"http://{host}:11434/v1"),
        ],
        allow_direct=True,
    )
    assert gateway.registry.list()[0].descriptor.is_local

"""Public copied client negotiates wire support without granting permission."""

import importlib.util
import json
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).parents[2] / "examples/studio_system_monitor"


def client(monkeypatch, response):
    spec = importlib.util.spec_from_file_location(
        "external_monitor", EXAMPLE / "monitor_client.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    host = module.StudioHost("http://127.0.0.1:8770", "fake-sdk-example-token")
    calls = []

    def request(path="", body=None, params=None):
        calls.append((path, body, params))
        return response

    monkeypatch.setattr(host, "request", request)
    return host, calls


def test_old_manifest_still_reviews_without_new_host_metadata(monkeypatch):
    host, calls = client(monkeypatch, {"digest": "sha256:" + "a" * 64})
    host.review(EXAMPLE / "nous.extension.json")
    assert [row[0] for row in calls] == ["/review"]


@pytest.mark.parametrize(
    "contract",
    [
        None,
        {"schema": "apeir.studio-ui/v99", "features": []},
        {"schema": "apeir.studio-ui/v1", "features": []},
    ],
)
def test_required_new_feature_is_refused_before_upload_or_install(
    monkeypatch, contract
):
    host, calls = client(monkeypatch, {"contract": contract})
    with pytest.raises(ValueError):
        host.install(EXAMPLE / "workflow-monitor.extension.json")
    assert [row[0] for row in calls] == [""]


def test_feature_discovery_does_not_grant_data_or_execute(monkeypatch):
    host, calls = client(
        monkeypatch,
        {
            "contract": {
                "schema": "apeir.studio-ui/v1",
                "features": ["data.workflow.summary"],
            }
        },
    )
    host.require_features(["data.workflow.summary"])
    assert calls == [("", None, None)]
    assert "Authorization" not in json.dumps(host.require_features([]))

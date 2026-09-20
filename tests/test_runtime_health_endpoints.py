from __future__ import annotations

from types import SimpleNamespace


def _stopped_process_local_status() -> SimpleNamespace:
    return SimpleNamespace(
        version="0.1.0-rc1",
        running=False,
        providers=0,
        capabilities=3,
        packs=0,
        devices=0,
        events_total=0,
        jobs_pending=0,
        demo_mode=False,
        errors=[],
    )


def test_detailed_health_reports_the_live_api_process(monkeypatch, tmp_path) -> None:
    from nous_runtime.api.health_endpoints import handle_health_detailed

    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "nous_runtime.kernel.runtime.Runtime.status",
        lambda _self: _stopped_process_local_status(),
    )

    response = handle_health_detailed()

    assert response["ok"] is True
    assert response["data"]["running"] is True
    assert response["data"]["ready"] is True
    assert response["data"]["status"] == "ok"


def test_runtime_status_reports_the_live_api_process(monkeypatch) -> None:
    from nous_runtime.api.health_endpoints import handle_runtime_status

    monkeypatch.setattr(
        "nous_runtime.kernel.runtime.Runtime.status",
        lambda _self: _stopped_process_local_status(),
    )

    response = handle_runtime_status()

    assert response["ok"] is True
    assert response["data"]["running"] is True

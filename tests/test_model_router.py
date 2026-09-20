from __future__ import annotations

import json

from typer.testing import CliRunner

from nous_runtime.intelligence.routing import (
    TASK_CODING,
    TASK_GENERAL,
    TASK_LOCAL,
    classify_task,
    route_model,
)


def _candidates() -> tuple[dict, ...]:
    return (
        {
            "provider_id": "deepseek",
            "name": "DeepSeek",
            "kind": "openai-compatible",
            "capabilities": ("model.reason", "model.code"),
            "health": "ok",
            "latency_ms": 300,
            "model": "deepseek-v4-flash",
            "local": False,
        },
        {
            "provider_id": "reasoning-only",
            "name": "Reasoning Only",
            "kind": "openai-compatible",
            "capabilities": ("model.reason",),
            "health": "ok",
            "latency_ms": 250,
            "model": "reasoning-model",
            "local": False,
        },
        {
            "provider_id": "ollama",
            "name": "Ollama",
            "kind": "ollama",
            "capabilities": ("model.reason", "model.code"),
            "health": "degraded",
            "latency_ms": 900,
            "model": "qwen3:8b",
            "local": True,
        },
    )


def test_classify_task_keywords():
    assert classify_task("fix this bug in my python function") == TASK_CODING
    assert classify_task("写一个Python程序") == TASK_CODING
    assert classify_task("帮我重构这段代码") == TASK_CODING
    assert classify_task("summarize this article for me") == TASK_GENERAL
    assert classify_task("今天天气怎么样") == TASK_GENERAL
    assert classify_task("answer this offline with ollama") == TASK_LOCAL
    assert classify_task("用本地模型回答") == TASK_LOCAL
    # local intent wins over coding keywords
    assert classify_task("run this code locally") == TASK_LOCAL
    # word-boundary matching: no false positive inside other words
    assert classify_task("scan this barcode") == TASK_GENERAL


def test_route_coding_selects_code_capable_provider():
    route = route_model("写一个Python程序", candidates=_candidates())
    assert route.task == TASK_CODING
    assert route.selected == "deepseek"
    assert "coding capability match" in route.reason
    assert "reasoning-only" not in (route.selected,)
    assert route.decision is not None
    assert route.decision.outcome.selected == "deepseek"


def test_route_coding_excludes_provider_without_code_capability():
    route = route_model(
        "debug this function",
        candidates=(
            {
                "provider_id": "reasoning-only",
                "capabilities": ("model.reason",),
                "health": "ok",
            },
            {
                "provider_id": "coder",
                "capabilities": ("model.reason", "model.code"),
                "health": "ok",
            },
        ),
    )
    assert route.selected == "coder"
    assert "reasoning-only" not in route.alternatives


def test_route_local_selects_local_provider():
    route = route_model("answer this offline please", candidates=_candidates())
    assert route.task == TASK_LOCAL
    assert route.selected == "ollama"
    assert "local provider preference" in route.reason


def test_route_local_without_local_provider_falls_back():
    route = route_model(
        "answer this offline please",
        candidates=(
            {
                "provider_id": "deepseek",
                "capabilities": ("model.reason", "model.code"),
                "health": "ok",
            },
        ),
    )
    assert route.task == TASK_LOCAL
    assert route.selected == "deepseek"
    assert "no local provider configured" in route.reason


def test_route_general_uses_reasoning_capability():
    route = route_model("summarize this article", candidates=_candidates())
    assert route.task == TASK_GENERAL
    assert route.selected
    assert "model.reason" in route.reason


def test_route_without_candidates_suggests_provider_add():
    route = route_model("hello", candidates=())
    assert route.selected == ""
    assert "nous provider add" in route.reason


def test_cli_model_route_test(monkeypatch):
    from nous_runtime.cli.main import app

    monkeypatch.setattr(
        "nous_runtime.intelligence.routing.default_candidates",
        lambda workspace=None: _candidates(),
    )

    result = CliRunner().invoke(app, ["model-route", "test", "写一个Python程序"])
    assert result.exit_code == 0
    assert "Task      coding" in result.stdout
    assert "Selected  deepseek" in result.stdout
    assert "Reason" in result.stdout

    json_result = CliRunner().invoke(
        app, ["model-route", "test", "写一个Python程序", "--json"]
    )
    assert json_result.exit_code == 0
    payload = json.loads(json_result.stdout)
    assert payload["task"] == "coding"
    assert payload["selected"] == "deepseek"
    assert payload["reason"]


def test_cli_model_route_test_without_providers(monkeypatch):
    from nous_runtime.cli.main import app

    monkeypatch.setattr(
        "nous_runtime.intelligence.routing.default_candidates",
        lambda workspace=None: (),
    )

    result = CliRunner().invoke(app, ["model-route", "test", "hello"])
    assert result.exit_code == 1
    assert "Selected  none" in result.stdout

from nous_runtime.governance.permission import (
    PermissionEngine,
    PermissionRequest,
    PermissionRule,
)


def test_permission_engine_models_subject_action_resource_context() -> None:
    engine = PermissionEngine(
        (
            PermissionRule(
                subject="agent:*",
                action="camera.read",
                resource="device:phone:*",
                context_equals={"locality": "local"},
            ),
        )
    )
    allowed = engine.check(
        PermissionRequest(
            "agent:reviewer",
            "camera.read",
            "device:phone:main",
            {"locality": "local"},
        )
    )
    denied = engine.check(
        PermissionRequest(
            "agent:reviewer",
            "camera.read",
            "device:phone:main",
            {"locality": "remote"},
        )
    )
    assert allowed.allowed is True
    assert denied.allowed is False


def test_explicit_deny_has_precedence() -> None:
    engine = PermissionEngine(
        (
            PermissionRule("*", "file.delete", "*", "allow"),
            PermissionRule("agent:*", "file.delete", "*", "deny"),
        )
    )
    decision = engine.check(
        PermissionRequest("agent:worker", "file.delete", "workspace:a")
    )
    assert decision.allowed is False
    assert decision.reason == "explicit deny"

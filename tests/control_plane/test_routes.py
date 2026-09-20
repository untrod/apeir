"""Tests for Control Plane API routes."""


class TestRouteTable:
    """Verify all expected routes are registered."""

    def test_control_plane_routes_registered(self):
        from nous_runtime.control_plane.routes import CONTROL_PLANE_ROUTES
        assert len(CONTROL_PLANE_ROUTES) >= 30
        # Runtime
        assert ("GET", "/api/v1/runtime/capabilities") in CONTROL_PLANE_ROUTES
        # Nodes
        assert ("POST", "/api/v1/nodes/{node_id}/enable") in CONTROL_PLANE_ROUTES
        assert ("POST", "/api/v1/nodes/{node_id}/test") in CONTROL_PLANE_ROUTES
        # Models
        assert ("GET", "/api/v1/models") in CONTROL_PLANE_ROUTES
        assert ("GET", "/api/v1/models/{model_id}") in CONTROL_PLANE_ROUTES
        assert ("POST", "/api/v1/models/{model_id}/test") in CONTROL_PLANE_ROUTES
        # Providers
        assert ("POST", "/api/v1/providers/validate") in CONTROL_PLANE_ROUTES
        assert ("POST", "/api/v1/providers") in CONTROL_PLANE_ROUTES
        assert ("PATCH", "/api/v1/providers/{provider_id}") in CONTROL_PLANE_ROUTES
        assert ("DELETE", "/api/v1/providers/{provider_id}") in CONTROL_PLANE_ROUTES
        # Tasks
        assert ("POST", "/api/v1/tasks/analyze") in CONTROL_PLANE_ROUTES
        assert ("POST", "/api/v1/tasks/plan") in CONTROL_PLANE_ROUTES
        assert ("POST", "/api/v1/tasks") in CONTROL_PLANE_ROUTES
        assert ("POST", "/api/v1/tasks/{task_id}/approve") in CONTROL_PLANE_ROUTES
        assert ("POST", "/api/v1/tasks/{task_id}/pause") in CONTROL_PLANE_ROUTES
        assert ("POST", "/api/v1/tasks/{task_id}/resume") in CONTROL_PLANE_ROUTES
        assert ("POST", "/api/v1/tasks/{task_id}/cancel") in CONTROL_PLANE_ROUTES
        assert ("POST", "/api/v1/tasks/{task_id}/retry") in CONTROL_PLANE_ROUTES
        assert ("GET", "/api/v1/tasks/{task_id}/events") in CONTROL_PLANE_ROUTES
        assert ("GET", "/api/v1/tasks/{task_id}/report") in CONTROL_PLANE_ROUTES
        # Conversations
        assert ("GET", "/api/v1/conversations") in CONTROL_PLANE_ROUTES
        assert ("POST", "/api/v1/conversations") in CONTROL_PLANE_ROUTES
        assert ("POST", "/api/v1/conversations/{conversation_id}/messages") in CONTROL_PLANE_ROUTES
        # Inspector/Decisions/Logs
        assert ("GET", "/api/v1/inspector/snapshot") in CONTROL_PLANE_ROUTES
        assert ("GET", "/api/v1/decisions") in CONTROL_PLANE_ROUTES
        assert ("GET", "/api/v1/logs") in CONTROL_PLANE_ROUTES

    def test_all_routes_have_handlers(self):
        from nous_runtime.control_plane.routes import CONTROL_PLANE_ROUTES
        for (method, path), handler in CONTROL_PLANE_ROUTES.items():
            assert callable(handler), f"Handler for {method} {path} is not callable"

    def test_governance_routes_registered(self):
        from nous_runtime.control_plane.routes import CONTROL_PLANE_GOVERNANCE
        assert len(CONTROL_PLANE_GOVERNANCE) >= 10
        # All mutation routes should have governance
        for key in CONTROL_PLANE_GOVERNANCE:
            assert key[0] in ("POST", "PATCH", "DELETE")


class TestRouteIntegration:
    """Test that routes integrate into the main ROUTES table."""

    def test_control_plane_in_main_routes(self):
        from nous_runtime.api.routes import ROUTES
        assert ("GET", "/api/v1/runtime/capabilities") in ROUTES
        assert ("GET", "/api/v1/tasks") in ROUTES
        assert ("POST", "/api/v1/tasks") in ROUTES
        assert ("GET", "/api/v1/models") in ROUTES


class TestHandlersReturnShape:
    """Verify handler responses follow the API envelope format."""

    def _is_valid_response(self, response):
        assert isinstance(response, dict)
        assert "ok" in response
        if response["ok"]:
            assert "data" in response
        else:
            assert "error" in response
            assert "code" in response["error"]
            assert "message" in response["error"]

    def test_capabilities_response(self):
        from nous_runtime.control_plane.routes import handle_runtime_capabilities
        resp = handle_runtime_capabilities()
        self._is_valid_response(resp)

    def test_list_tasks_response(self):
        from nous_runtime.control_plane.routes import handle_list_tasks_ctrl
        resp = handle_list_tasks_ctrl()
        self._is_valid_response(resp)
        if resp["ok"]:
            assert "tasks" in resp["data"]
            assert "pagination" in resp["data"]

    def test_list_tasks_query_is_passed_as_a_parameter_map(self):
        from nous_runtime.api.routes import route_server

        resp = route_server("GET", "/api/v1/tasks", params={"limit": "5"})

        self._is_valid_response(resp)
        assert resp.get("error", {}).get("code") != "NOUS_INTERNAL_ERROR"
        if resp["ok"]:
            assert resp["data"]["pagination"]["page_size"] == 5

    def test_list_models_response(self):
        from nous_runtime.control_plane.routes import handle_list_models
        resp = handle_list_models()
        self._is_valid_response(resp)
        if resp["ok"]:
            assert "models" in resp["data"]
            assert "pagination" in resp["data"]

    def test_inspector_snapshot_response(self):
        from nous_runtime.control_plane.routes import handle_inspector_snapshot
        resp = handle_inspector_snapshot()
        self._is_valid_response(resp)
        if resp["ok"]:
            assert "runtime" in resp["data"]
            assert "providers" in resp["data"]

    def test_logs_response(self):
        from nous_runtime.control_plane.routes import handle_logs
        resp = handle_logs()
        self._is_valid_response(resp)
        if resp["ok"]:
            assert "entries" in resp["data"]

    def test_list_conversations_response(self):
        from nous_runtime.control_plane.routes import handle_list_conversations
        resp = handle_list_conversations()
        self._is_valid_response(resp)


class TestInputValidation:
    """Test that handlers validate required inputs."""

    def test_analyze_requires_input_text(self):
        from nous_runtime.control_plane.routes import handle_task_analyze
        resp = handle_task_analyze({"input_text": ""})
        assert resp["ok"] is False
        assert resp["error"]["code"] == "NOUS_VALIDATION_ERROR"

    def test_create_task_requires_title(self):
        from nous_runtime.control_plane.routes import handle_create_task
        resp = handle_create_task({"title": ""})
        assert resp["ok"] is False
        assert resp["error"]["code"] == "NOUS_VALIDATION_ERROR"

    def test_create_provider_requires_id_and_name(self):
        from nous_runtime.control_plane.routes import handle_create_provider
        resp = handle_create_provider({"provider_id": "", "name": ""})
        assert resp["ok"] is False

    def test_validate_provider_requires_id_and_name(self):
        from nous_runtime.control_plane.routes import handle_validate_provider
        resp = handle_validate_provider({"provider_id": "", "name": ""})
        assert resp["ok"] is False
        assert resp["error"]["code"] == "NOUS_VALIDATION_ERROR"

    def test_validate_provider_is_read_only(self, monkeypatch):
        from nous_runtime.control_plane.routes import handle_validate_provider

        captured = {}

        def validate_provider_from_config(**values):
            captured.update(values)
            return {"ok": True, "status": "healthy", "latency_ms": 12}

        monkeypatch.setattr(
            "nous_runtime.cli.provider_setup.validate_provider_from_config",
            validate_provider_from_config,
        )
        resp = handle_validate_provider({
            "provider_id": "deepseek",
            "name": "DeepSeek",
            "api_base_url": "https://api.deepseek.com/v1",
            "credential_ref": "env:DEEPSEEK_API_KEY",
            "capabilities": ["chat", "reasoning"],
        })

        assert resp["ok"] is True
        assert resp["data"]["status"] == "healthy"
        assert captured["credential_ref"] == "env:DEEPSEEK_API_KEY"

    def test_create_message_requires_content(self):
        from nous_runtime.control_plane.routes import handle_create_message
        resp = handle_create_message("conv_1", {"content": "", "role": "user"})
        assert resp["ok"] is False


class TestPagination:
    """Test pagination helper."""

    def test_paginate_basic(self):
        from nous_runtime.control_plane.routes import _paginate
        items = list(range(100))
        result = _paginate(items, 1, 20)
        assert len(result["items"]) == 20
        assert result["pagination"]["total"] == 100
        assert result["pagination"]["total_pages"] == 5
        assert result["pagination"]["has_next"] is True
        assert result["pagination"]["has_prev"] is False

    def test_paginate_last_page(self):
        from nous_runtime.control_plane.routes import _paginate
        items = list(range(100))
        result = _paginate(items, 5, 20)
        assert len(result["items"]) == 20
        assert result["pagination"]["has_next"] is False
        assert result["pagination"]["has_prev"] is True

    def test_paginate_empty(self):
        from nous_runtime.control_plane.routes import _paginate
        result = _paginate([], 1, 50)
        assert len(result["items"]) == 0
        assert result["pagination"]["total"] == 0

    def test_parse_pagination_defaults(self):
        from nous_runtime.control_plane.routes import _parse_pagination
        page, page_size, sort_by, sort_order = _parse_pagination({})
        assert page == 1
        assert page_size == 50
        assert sort_by is None
        assert sort_order == "asc"

    def test_parse_pagination_custom(self):
        from nous_runtime.control_plane.routes import _parse_pagination
        page, page_size, sort_by, sort_order = _parse_pagination({
            "page": "3", "page_size": "25", "sort_by": "created_at", "sort_order": "desc",
        })
        assert page == 3
        assert page_size == 25
        assert sort_by == "created_at"
        assert sort_order == "desc"


class TestTaskAnalyze:
    """Test the analyze endpoint with real inputs."""

    def test_analyze_code_task(self):
        from nous_runtime.control_plane.routes import handle_task_analyze
        resp = handle_task_analyze({"input_text": "Write a Python function to sort a list"})
        assert resp["ok"] is True
        assert resp["data"]["intent"] == "code_task"
        assert len(resp["data"]["required_capabilities"]) >= 1

    def test_analyze_research_task(self):
        from nous_runtime.control_plane.routes import handle_task_analyze
        resp = handle_task_analyze({"input_text": "Research the best approach for distributed caching"})
        assert resp["ok"] is True
        assert resp["data"]["intent"] == "research"

    def test_analyze_detects_approval_needed(self):
        from nous_runtime.control_plane.routes import handle_task_analyze
        resp = handle_task_analyze({"input_text": "Delete all production databases"})
        assert resp["ok"] is True
        assert resp["data"]["requires_approval"] is True

    def test_analyze_detects_risks(self):
        from nous_runtime.control_plane.routes import handle_task_analyze
        resp = handle_task_analyze({"input_text": "Deploy to production with sudo access"})
        assert resp["ok"] is True
        risks = resp["data"].get("risks", [])
        assert len(risks) >= 1


class TestRedaction:
    """Verify no sensitive data leaks in responses."""

    def test_provider_response_masks_credentials(self):
        from nous_runtime.control_plane.schemas import ProviderResponse
        # Credential refs should be masked
        p = ProviderResponse(
            provider_id="test", name="Test",
            credential_ref="env:MY_SECRET_KEY",
        )
        d = p.model_dump()
        assert "MY_SECRET_KEY" not in str(d.get("credential_ref", ""))

    def test_node_response_masks_credentials(self):
        from nous_runtime.control_plane.schemas import NodeResponse
        n = NodeResponse(
            node_id="n1", node_name="test", node_role="personal_node",
            platform_os="Windows", platform_arch="x86_64", platform_hostname="test",
            runtime_tier="full", word_size_bits=64,
            credential_id="cred_secret_value_12345",
        )
        d = n.model_dump()
        assert "secret_value" not in str(d.get("credential_id", ""))

    def test_schemas_no_password_fields(self):
        """No schema should have a plaintext password field."""
        import inspect
        from nous_runtime.control_plane import schemas
        for name, obj in inspect.getmembers(schemas):
            if inspect.isclass(obj) and name.endswith("Request"):
                for field_name in getattr(obj, 'model_fields', {}):
                    assert "password" not in field_name.lower()
                    assert "secret" not in field_name.lower()
                    assert "key" not in field_name.lower() or "request" in field_name.lower() or "idempotency" in field_name.lower()

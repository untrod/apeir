"""Authenticated data-only Studio host API; mutations use the existing Gate."""

from __future__ import annotations

import os
from pathlib import Path
import re

from nous_runtime.api.responses import err_response, ok_response
from nous_runtime.extensions.presentation import StudioExtensionHost


def workspace():
    return (
        Path(os.environ.get("NOUS_WORKSPACE_ROOT") or Path.cwd()).expanduser().resolve()
    )


def _admit(context, *, permission="workspace.read"):
    from nous_runtime.governance import ActionProposal, get_gate
    from nous_runtime.governance.contracts import AuthorizationContext
    from nous_runtime.control_plane.human_sessions import is_human_session_context

    if not isinstance(context, AuthorizationContext):
        raise PermissionError("Authenticated Studio identity is required")
    gate = get_gate()
    if context.authn_method == "oidc_pkce" and not is_human_session_context(
        context, gate.store
    ):
        raise PermissionError("Original human session is no longer current")
    decision = gate.evaluate(
        ActionProposal(
            capability_id="project.read_file",
            action_type="studio.extension.inspect",
            target_workspace=str(workspace()),
            affected_resources=(
                str(workspace() / ".nous" / "extensions" / "registry.json"),
            ),
            required_permissions=(permission,),
            side_effect_class="read_only",
            reversibility="reversible",
            retry_behavior="idempotent",
            locality=context.session_locality,
        ),
        context,
    )
    if decision.action_mode != "EXECUTE" or decision.allowed is not True:
        raise PermissionError("Studio extension access was not admitted")
    return StudioExtensionHost(workspace())


def _exact(body, required):
    if not isinstance(body, dict) or set(body) != set(required):
        raise ValueError("Unsupported or missing Studio host argument")


def _digest(value, *, empty=False):
    if not isinstance(value, str) or (
        not (empty and value == "") and not re.fullmatch(r"sha256:[0-9a-f]{64}", value)
    ):
        raise ValueError("A reviewed SHA-256 binding is required")
    return value


def _component(params):
    component = params.get("component_type")
    if not isinstance(component, str) or not re.fullmatch(
        r"ui:[0-9a-f]{32}:[a-z][a-z0-9-]{0,31}", component
    ):
        raise ValueError("Invalid Studio component type")
    return component, _digest(params.get("expected_digest"))


def _result(call):
    try:
        return ok_response(call())
    except PermissionError:
        raise
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as error:
        return err_response("NOUS_INVALID_REQUEST", str(error))


def handle_studio_extensions(*, authorization_context=None):
    host = _admit(authorization_context)
    return _result(host.view)


def handle_studio_extension_review(body, *, authorization_context=None):
    host = _admit(authorization_context)

    def review():
        _exact(body, {"source_manifest"})
        return host.review(body["source_manifest"])

    return _result(review)


def handle_studio_extension_install(body, *, authorization_context=None):
    host = _admit(authorization_context)

    def install():
        _exact(body, {"source_manifest", "expected_digest", "expected_previous_digest"})
        return host.install(
            body["source_manifest"],
            expected_digest=_digest(body["expected_digest"]),
            expected_previous_digest=_digest(
                body["expected_previous_digest"], empty=True
            ),
            before_publish=lambda: _admit(
                authorization_context, permission="workspace.write"
            ),
        )

    return _result(install)


def handle_studio_extension_configure(body, *, authorization_context=None):
    host = _admit(authorization_context)

    def configure():
        _exact(body, {"extension_id", "enabled", "expected_digest", "expected_version"})
        return host.configure(
            body["extension_id"],
            enabled=body["enabled"],
            expected_digest=_digest(body["expected_digest"]),
            expected_version=body["expected_version"],
            before_publish=lambda: _admit(
                authorization_context, permission="workspace.write"
            ),
        )

    return _result(configure)


def handle_studio_extension_remove(body, *, authorization_context=None):
    host = _admit(authorization_context)

    def remove():
        _exact(body, {"extension_id", "expected_digest", "expected_version"})
        return host.remove(
            body["extension_id"],
            expected_digest=_digest(body["expected_digest"]),
            expected_version=body["expected_version"],
            before_remove=lambda: _admit(
                authorization_context, permission="workspace.write"
            ),
        )

    return _result(remove)


def handle_studio_extension_data(params=None, *, authorization_context=None):
    host = _admit(authorization_context)

    def data():
        values = params or {}
        _exact(values, {"component_type", "expected_digest", "source"})
        component, digest = _component(values)
        return host.read_data(component, digest, values["source"])

    return _result(data)


def handle_studio_extension_events(params=None, *, authorization_context=None):
    host = _admit(authorization_context)

    def events():
        values = params or {}
        _exact(values, {"component_type", "expected_digest"})
        component, digest = _component(values)
        return host.read_events(component, digest)

    return _result(events)


def handle_studio_extension_action(body, *, authorization_context=None):
    host = _admit(authorization_context, permission="workflow.execute")

    def action():
        _exact(body, {"component_type", "expected_digest", "action", "idempotency_key"})
        component, digest = _component(body)
        return host.request_action(
            component, digest, body["action"], idempotency_key=body["idempotency_key"]
        )

    return _result(action)


STUDIO_EXTENSION_ROUTES = {
    ("GET", "/api/v1/studio/extensions"): handle_studio_extensions,
    ("POST", "/api/v1/studio/extensions/review"): handle_studio_extension_review,
    ("POST", "/api/v1/studio/extensions/install"): handle_studio_extension_install,
    ("POST", "/api/v1/studio/extensions/configure"): handle_studio_extension_configure,
    ("POST", "/api/v1/studio/extensions/remove"): handle_studio_extension_remove,
    ("GET", "/api/v1/studio/extensions/data"): handle_studio_extension_data,
    ("GET", "/api/v1/studio/extensions/events"): handle_studio_extension_events,
    ("POST", "/api/v1/studio/extensions/action"): handle_studio_extension_action,
}
STUDIO_EXTENSION_GOVERNANCE = {
    ("POST", "/api/v1/studio/extensions/install"): (
        "extension.ui.install",
        "local_write",
        "partially_reversible",
    ),
    ("POST", "/api/v1/studio/extensions/configure"): (
        "extension.ui.configure",
        "local_write",
        "partially_reversible",
    ),
    ("POST", "/api/v1/studio/extensions/remove"): (
        "extension.ui.remove",
        "local_write",
        "partially_reversible",
    ),
    ("POST", "/api/v1/studio/extensions/action"): (
        "workflow.run",
        "local_write",
        "partially_reversible",
    ),
}


def studio_mutation_summary(route_path, body, authorization_context):
    """Bind reviewed source bytes by digest, never log/upload raw manifest text."""
    values = body or {}
    if route_path.endswith("/install"):
        _exact(
            values, {"source_manifest", "expected_digest", "expected_previous_digest"}
        )
        host = _admit(authorization_context)
        reviewed = host.review(values["source_manifest"])
        return {
            "extension_id": reviewed["extension_id"],
            "version": reviewed["version"],
            "package_digest": reviewed["digest"],
            "expected_digest": _digest(values["expected_digest"]),
            "expected_previous_digest": _digest(
                values["expected_previous_digest"], empty=True
            ),
        }
    if route_path.endswith("/configure"):
        _exact(
            values, {"extension_id", "enabled", "expected_digest", "expected_version"}
        )
        if type(values["enabled"]) is not bool:
            raise ValueError("Presentation enabled must be boolean")
    elif route_path.endswith("/remove"):
        _exact(values, {"extension_id", "expected_digest", "expected_version"})
    elif route_path.endswith("/action"):
        _exact(
            values, {"component_type", "expected_digest", "action", "idempotency_key"}
        )
        _component(values)
        if values["action"] != "workflow.run":
            raise ValueError("Unsupported governed Studio action")
    else:
        raise ValueError("Unsupported Studio mutation")
    _digest(values["expected_digest"])
    return dict(values)

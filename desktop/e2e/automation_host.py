"""Test-only HTTP host with a cryptographic fake IdP, never production identity.

The browser still uses the real challenge, PKCE, signed ID token, session cookie,
one-use mutation nonce and Governance checks. No model or physical effect is
qualified by this fixture. Imports also work against the installed source wheel.
"""

import argparse
from pathlib import Path
import signal
from threading import Event, Thread
import time
from types import SimpleNamespace

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import jwt

from nous_runtime.api.server import RuntimeAPIHandler, RuntimeHTTPServer
from nous_runtime.control_plane import human_sessions
from nous_runtime.control_plane.human_sessions import (
    HumanSessionAuth,
    OIDCHumanIdentityProvider,
)
from nous_runtime.governance import GovernanceStore, get_gate
from nous_runtime.governance.permission import PermissionEngine, PermissionRule


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--decision-recovery", action="store_true")
    args = parser.parse_args()
    # Deterministic FAKE key and subject, restricted to this isolated test host.
    key = Ed25519PrivateKey.from_private_bytes(b"a" * 32)
    issuer = "https://automation-identity.example.invalid"

    def exchange(*_args, **kwargs):
        code = kwargs["code"]
        if not code.startswith("fake-automation-code:"):
            raise PermissionError("Test IdP code refused")
        now = int(time.time())
        claims = {
            "iss": issuer,
            "sub": "test-operator",
            "aud": "apeir-automation-browser",
            "iat": now,
            "exp": now + 600,
            "auth_time": now,
            "amr": ["mfa"],
            "nonce": code.removeprefix("fake-automation-code:"),
        }
        return {"id_token": jwt.encode(claims, key, algorithm="EdDSA")}

    provider = OIDCHumanIdentityProvider(
        {
            "issuer": issuer,
            "client_id": "apeir-automation-browser",
            "redirect_uri": "http://127.0.0.1:5184/",
            "authorization_endpoint": issuer + "/authorize",
            "token_endpoint": issuer + "/token",
            "jwks_uri": issuer + "/keys",
            "subjects": ["test-operator"],
        },
        jwk_client=SimpleNamespace(
            get_signing_key_from_jwt=lambda _: SimpleNamespace(key=key.public_key())
        ),
        oauth_client=SimpleNamespace(fetch_token=exchange),
    )
    gate = get_gate(GovernanceStore(Path(args.workspace) / ".nous"))
    human_sessions._configured_auth = HumanSessionAuth(
        gate.store,
        provider,
        permissions=PermissionEngine(
            tuple(
                PermissionRule("oidc:*:test-operator", action, "*")
                for action in ("control.*", "governance.approve", "workspace.read")
            )
        ),
    )
    supervisor = None
    if args.decision_recovery:
        from nous_runtime.model_runtime import GatewayResponse
        from nous_runtime.work import WorkHarness, WorkSupervisor, ModelWorkDeliberator
        from nous_runtime.work.components import WorkExecutionComponents
        from nous_runtime.work.supervisor import _SUPERVISORS

        class FixtureFacade:
            """Deliberately invalid first response, not real model qualification."""

            def try_invoke_sync(self, request):
                events = WorkHarness(args.workspace).events.load_events(
                    request.execution.session_id
                )
                rejected = any(
                    event.event_type == "work.model.invalid" for event in events
                )
                return GatewayResponse(
                    request_id="fixture-decision-request",
                    model_id="fixture/recovery-model",
                    structured_output={
                        "status": "complete" if rejected else "replan",
                        "summary": "Recovered the original request"
                        if rejected
                        else "Invalid plan",
                        "confidence": "high",
                        "output": "Original request restored" if rejected else None,
                    },
                )

        supervisor = WorkSupervisor(
            args.workspace,
            component_factory=lambda *_: WorkExecutionComponents(
                tools=None,
                deliberator=ModelWorkDeliberator(FixtureFacade()),
                verifier=None,
            ),
        )
        _SUPERVISORS[str(Path(args.workspace).resolve())] = supervisor
    server = RuntimeHTTPServer(("127.0.0.1", args.port), RuntimeAPIHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    stop = Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    thread.start()
    try:
        stop.wait()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        if supervisor is not None:
            supervisor.close()
        if thread.is_alive():
            raise RuntimeError("Owned test HTTP host did not stop normally")


if __name__ == "__main__":
    main()

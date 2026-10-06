"""Exercise real OAuth/JWKS libraries over fake local TLS, not human qualification."""

import base64
import hashlib
import ipaddress
import json
import ssl
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from nous_runtime.control_plane.human_sessions import (
    HumanSessionAuth,
    OIDCHumanIdentityProvider,
)
from nous_runtime.governance.permission import PermissionEngine, PermissionRule
from nous_runtime.governance.broker import ApprovalBroker
from tests.control_plane.test_human_sessions import (
    human_env as human_env_fixture,
    operation,
)

human_env = human_env_fixture
pytestmark = pytest.mark.integration
FAKE_CODE = "m35q.fake.oidc.transport.code"
VERIFIER = "m35q.fake.pkce.verifier." + "z" * 64


@pytest.fixture
def oidc_tls(tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "APEIR fake test IdP")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    certificate = tmp_path / "fake-idp.pem"
    private_key = tmp_path / "fake-idp.key"
    certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private_key.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    state = {
        "mode": "valid",
        "nonce": "",
        "token_calls": 0,
        "redirect_calls": 0,
        "key_calls": 0,
    }
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())) | {
        "kid": "fake-signing-key",
        "use": "sig",
        "alg": "RS256",
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            return

        def reply(self, status, payload):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            state["key_calls"] += 1
            self.reply(200, {"keys": [jwk]})

        def do_POST(self):
            if self.path == "/redirected-token":
                state["redirect_calls"] += 1
                self.reply(500, {"error": "unexpected_redirect"})
                return
            state["token_calls"] += 1
            params = parse_qs(
                self.rfile.read(int(self.headers["Content-Length"])).decode()
            )
            if (
                params.get("code") != [FAKE_CODE]
                or params.get("code_verifier") != [VERIFIER]
                or params.get("grant_type") != ["authorization_code"]
            ):
                self.reply(400, {"error": "invalid_grant"})
                return
            if state["mode"] == "redirect":
                self.send_response(307)
                self.send_header("Location", state["issuer"] + "/redirected-token")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if state["mode"] == "unavailable":
                self.reply(503, {"error": "temporarily_unavailable"})
                return
            stamp = int(time.time())
            claims = {
                "iss": state["issuer"],
                "aud": "apeir-test",
                "sub": "alice",
                "iat": stamp,
                "exp": stamp + 300,
                "auth_time": stamp,
                "nonce": state["nonce"],
                "amr": ["mfa"],
            }
            if state["mode"] == "nonce":
                claims["nonce"] = "m35q.fake.unbound.nonce"
            if state["mode"] == "issuer":
                claims["iss"] = "https://other.example.test"
            token = jwt.encode(
                claims, key, algorithm="RS256", headers={"kid": "fake-signing-key"}
            )
            self.reply(
                200,
                {
                    "id_token": token,
                    "access_token": "m35q.fake.access.material",
                    "token_type": "Bearer",
                    "expires_in": 300,
                },
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state["issuer"] = f"https://127.0.0.1:{server.server_port}"
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, private_key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(certificate))
    # Only this ephemeral test CA is trusted; verification is never disabled.
    trusted = ssl.create_default_context(cafile=str(certificate))
    try:
        yield state, trusted
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize(
    "mode", ["valid", "nonce", "issuer", "redirect", "unavailable", "untrusted_tls"]
)
def test_real_oauth_and_jwks_transport_preserves_existing_authority(
    human_env, oidc_tls, mode
):
    gate, _, _, _ = human_env
    state, tls = oidc_tls
    state["mode"] = mode
    if mode == "untrusted_tls":
        tls = ssl.create_default_context()
    issuer = state["issuer"]
    provider = OIDCHumanIdentityProvider(
        {
            "issuer": issuer,
            "client_id": "apeir-test",
            "redirect_uri": "https://console.example.test/",
            "authorization_endpoint": issuer + "/authorize",
            "token_endpoint": issuer + "/token",
            "jwks_uri": issuer + "/keys",
            "subjects": ["alice"],
        },
        jwk_client=jwt.PyJWKClient(issuer + "/keys", ssl_context=tls, timeout=2),
    )
    subject = "oidc:" + hashlib.sha256(issuer.encode()).hexdigest()[:16] + ":alice"
    auth = HumanSessionAuth(
        gate.store,
        provider,
        permissions=PermissionEngine(
            (PermissionRule(subject, "governance.approve", "device-1"),)
        ),
    )
    pkce = (
        base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest())
        .decode()
        .rstrip("=")
    )
    challenge = auth.challenge(pkce)
    state["nonce"] = parse_qs(urlsplit(challenge["authorization_url"]).query)["nonce"][
        0
    ]
    request, pending = operation(gate)
    if mode != "valid":
        with pytest.raises(PermissionError, match="authentication failed"):
            auth.login(challenge["challenge_id"], FAKE_CODE, VERIFIER)
        with pytest.raises(PermissionError):
            auth.login(challenge["challenge_id"], FAKE_CODE, VERIFIER)
        assert gate.store.list_active_leases() == []
        assert (
            gate.store.get_approval_request(pending.request_id)["status"] == "PENDING"
        )
    else:
        issued = auth.login(challenge["challenge_id"], FAKE_CODE, VERIFIER)
        context = auth.authenticate(issued.session_cookie)
        response = ApprovalBroker(gate.store).respond_operation(
            pending.request_id, "approve", context, gate=gate
        )
        assert response.approver_id == subject
        assert gate.get_operation_request(request.authorization_id) == request
        assert state["key_calls"] == 1
        assert gate.store.verify_audit_chain()
        audit = json.dumps(gate.store.operation_audit())
        assert all(
            value not in audit
            for value in (
                FAKE_CODE,
                VERIFIER,
                issued.session_cookie,
                "m35q.fake.access.material",
            )
        )
    assert state["token_calls"] == 1
    assert state["redirect_calls"] == 0

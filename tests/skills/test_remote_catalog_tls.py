"""Actual child-process HTTPS bytes; fixture routing does not qualify public catalogs."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import time

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from nous_runtime.evidence.web_gateway import WebGateway, WebRequest
from nous_runtime.skills import SkillRegistry
from tests.skills.test_skill_registry import make_skill
from tests.skills.test_remote_catalog import bundle

SERVER = """import http.server, socketserver, ssl, sys
from pathlib import Path
root=Path(sys.argv[1])
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(root),**kwargs)
    def log_message(self,*args): pass
    def do_GET(self):
        if self.path == "/redirect.zip":
            self.send_response(302)
            self.send_header("Location", "/code-helper.zip")
            self.send_header("Content-Length", "0")
            self.end_headers()
        else: super().do_GET()
class LocalServer(http.server.ThreadingHTTPServer):
    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name,self.server_port=self.server_address[:2]
server=LocalServer(("127.0.0.1",0),Handler)
context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(root/"test.pem",root/"test.key")
server.socket=context.wrap_socket(server.socket,server_side=True)
(root/"port.pending").write_text(str(server.server_port))
(root/"port.pending").replace(root/"port")
server.serve_forever()
"""


@pytest.fixture
def tls_catalog(tmp_path, monkeypatch):
    root = tmp_path / "server"
    root.mkdir()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fake skill catalog")])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("catalog.example.test"),
                    x509.DNSName("packages.example.test"),
                ]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    (root / "test.pem").write_bytes(
        certificate.public_bytes(serialization.Encoding.PEM)
    )
    (root / "test.key").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    (root / "test.key").chmod(0o600)
    script = tmp_path / "fake_catalog_server.py"
    script.write_text(SERVER)
    process = subprocess.Popen(
        [sys.executable, str(script), str(root)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 5
        while (
            not (root / "port").exists()
            and process.poll() is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        assert (root / "port").exists(), "fake local TLS server failed to start"
        port = int((root / "port").read_text())
        source = make_skill(tmp_path / "source" / "code-helper")
        inspector = SkillRegistry(tmp_path / "inspect")
        inspector.add_catalog(str(source.parent))
        entry = inspector.catalog_records()[0]
        package_url = f"https://packages.example.test:{port}/code-helper.zip"
        catalog_url = f"https://catalog.example.test:{port}/catalog.json"
        raw = dict(
            name=entry.skill_id,
            description=entry.description,
            version=entry.version,
            digest=entry.digest,
            source=package_url,
            requested_capabilities=list(entry.requested_capabilities),
        )
        (root / "code-helper.zip").write_bytes(bundle(source))
        (root / "catalog.json").write_text(
            json.dumps({"schema": "apeir.skill-catalog/v1", "skills": [raw]})
        )
        monkeypatch.setenv("SSL_CERT_FILE", str(root / "test.pem"))
        monkeypatch.setattr(
            WebGateway,
            "_resolve_public_addresses",
            staticmethod(lambda *_: ["8.8.8.8"]),
        )
        original_connect = socket.create_connection
        connections = []

        def fixture_route(address, *args, **kwargs):
            # Central address checks still happen first; only this owned server
            # endpoint is redirected by the test seam, with TLS/SNI unchanged.
            assert address == ("8.8.8.8", port)
            connections.append(address)
            return original_connect(("127.0.0.1", port), *args, **kwargs)

        monkeypatch.setattr(socket, "create_connection", fixture_route)
        yield root, catalog_url, package_url, entry, connections
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_real_child_tls_catalog_install_and_independent_registry_reload(
    tls_catalog, tmp_path
):
    root, catalog_url, package_url, entry, connections = tls_catalog
    registry = SkillRegistry(tmp_path / "workspace")
    permissions = []

    def human():
        return None  # fake trusted-host contract; not a live human identity

    def authorize(url):
        assert url in {catalog_url, package_url}
        permissions.append(url)

    registry.add_catalog(catalog_url, before_publish=human, authorize_remote=authorize)
    acquired = WebGateway().fetch_bytes(WebRequest(url=package_url, max_redirects=0))
    assert acquired.body == (root / "code-helper.zip").read_bytes()
    assert acquired.response.content_hash == hashlib.sha256(acquired.body).hexdigest()
    count = len(connections)
    registry.list()
    registry.search("helper")
    assert len(connections) == count
    installed = registry.install_from_catalog(
        entry.skill_id,
        catalog_source=catalog_url,
        package_source=package_url,
        version=entry.version,
        digest=entry.digest,
        before_publish=human,
        authorize_remote=authorize,
    )
    assert (
        installed.digest == entry.digest and installed.metadata["authority"] == "none"
    )
    # A fresh consumer verifies the same durable Extension and CAS bytes, with
    # no fixture transport/route override and no network acquisition.
    consumer = subprocess.run(
        [
            sys.executable,
            "-c",
            "from nous_runtime.skills import SkillRegistry; import sys; r=SkillRegistry(sys.argv[1]); s=r.load('installed:code-helper'); assert s.digest==sys.argv[2]; assert s.metadata['authority']=='none'; assert r.catalog_records()[0].source==sys.argv[3]",
            str(registry.workspace),
            entry.digest,
            package_url,
        ],
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert consumer.returncode == 0, consumer.stderr
    assert package_url in permissions
    assert not (
        registry.extensions.package_path("skills/code-helper") / "executed"
    ).exists()


@pytest.mark.parametrize("mode", ["redirect", "limit", "hostname", "untrusted"])
def test_real_tls_rejections_return_no_binary_bytes(tls_catalog, monkeypatch, mode):
    _, _, package_url, _, connections = tls_catalog
    request = WebRequest(url=package_url, max_redirects=0)
    if mode == "redirect":
        request.url = package_url.replace("code-helper.zip", "redirect.zip")
    elif mode == "limit":
        request.max_size_bytes = 16
    elif mode == "hostname":
        request.url = package_url.replace("packages.example.test", "wrong.example.test")
    else:
        monkeypatch.delenv("SSL_CERT_FILE")
    result = WebGateway().fetch_bytes(request)
    assert connections and not result.response.ok and result.body == b""
    expected = {
        "redirect": "NETWORK_REDIRECT_LIMIT",
        "limit": "NETWORK_RESPONSE_TOO_LARGE",
        "hostname": "NETWORK_TLS_FAILED",
        "untrusted": "NETWORK_TLS_FAILED",
    }
    assert result.response.error_code == expected[mode]

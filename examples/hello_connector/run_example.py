from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from nous_runtime.connectors import ConnectorManifest, ConnectorRequest, ConnectorRuntime, ConnectorStore, LocalFileConnector, MemoryTokenVault
from nous_runtime.governance import AuthorizationContext


class ApprovalRequiredGate:
    def evaluate(self, proposal, context):
        return SimpleNamespace(action_mode="ASK_APPROVAL", reason_message="Approval required", reason_code="APPROVAL_REQUIRED")


def main() -> None:
    manifest_path = Path(__file__).with_name("connector.json")
    manifest = ConnectorManifest.from_dict(json.loads(manifest_path.read_text(encoding="utf-8")))
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "hello.txt").write_text("Hello from Nous", encoding="utf-8")
        store = ConnectorStore(root)
        store.register(manifest)
        runtime = ConnectorRuntime(store, MemoryTokenVault(), gate=ApprovalRequiredGate())
        runtime.bind(manifest.connector_id, LocalFileConnector(root))
        context = AuthorizationContext(subject_type="user", subject_id="example-user", authn_method="cli_os_user", authn_confidence=1.0)
        read = runtime.execute(ConnectorRequest(manifest.connector_id, "read", "example", {"path": "hello.txt"}), context=context)
        denied = runtime.execute(ConnectorRequest(manifest.connector_id, "write", "example", {"path": "changed.txt", "content": "blocked"}), context=context)
        assert read.ok and denied.error_code == "AUTHORIZATION_REQUIRED"


if __name__ == "__main__":
    main()
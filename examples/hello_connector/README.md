# Hello Connector

A first-party contract example for `ConnectorStore`, `ConnectorRuntime` and a
workspace-bound `LocalFileConnector`. Run it from the checkout after installing
Distribution using [Developer Setup](../../docs/operations/getting-started/QUICK_START.md#developer-setup):

```bash
python examples/hello_connector/run_example.py
```

The example creates a temporary `hello.txt`, reads it and verifies that a write
returns `AUTHORIZATION_REQUIRED`; `changed.txt` is not written. Successful
completion exits 0 without printing a result. The temporary workspace is removed.

`ApprovalRequiredGate` is a test double which always asks for approval. This does
not log in a real human, approve a write or qualify production Governance. The
public Provider example and [Verified Demo](../hello_runtime/README.md) cover
separate execution paths; do not reuse the test double as an authorization host.

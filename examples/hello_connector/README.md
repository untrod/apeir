# Hello Connector

This example loads `connector.json`, registers it in the existing ConnectorStore, binds the workspace-scoped LocalFileConnector, and executes through ConnectorRuntime. Read access remains inside the temporary workspace; the write action is denied until Governance returns `EXECUTE`. The temporary workspace is deleted automatically.

Run:

```console
python examples/hello_connector/run_example.py
```
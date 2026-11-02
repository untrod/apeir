"""Request the registered example Workflow; inspect approval before execution."""

import os

from nous_provider.runtime import NousClient

runtime = NousClient(token=os.environ.get("NOUS_API_TOKEN", ""))
response = runtime.workflow(
    "example.workflow", {"message": "Hello, Nous"}, idempotency_key="python-sdk-example"
)
print(response)
if not response.get("ok"):
    raise SystemExit(2)

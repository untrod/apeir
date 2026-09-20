import os

from nous_runtime.sdk import NousClient

runtime = NousClient(token=os.environ.get("NOUS_API_TOKEN", ""))
response = runtime.workflow("example.workflow", {"message": "Hello, Nous"}, idempotency_key="python-sdk-example")
print(response)
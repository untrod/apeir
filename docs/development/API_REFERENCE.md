# Runtime HTTP API reference

<!-- Compatibility anchors for existing documentation links. -->
<a name="apeir-runtime-api-reference-v10"></a>


The local Runtime API normally listens on `http://127.0.0.1:8770`. Start the
model-free service through [Quick Start](../operations/getting-started/QUICK_START.md).
This page identifies supported entry points; the [desktop API contract](../../desktop/API_CONTRACT.md)
and actual route handlers contain the detailed request/response definitions.
API/schema versions are separate from the Distribution package version.

## HTTP API

### Authentication

Use `Authorization: Bearer <runtime-session-token>` for protected endpoints.
The legacy `X-Auth-Token` header remains a compatibility path. Tokens in query
strings are refused; do not put credentials in URLs, examples or shell history.
The Runtime session token is not a Provider API key or human approval.

A successful authenticated request still needs the current workspace permission.
Mutations may require an independent human session/nonce or approval of the
original request. A service credential cannot approve itself. Read-only discovery
does not grant permission to invoke a capability.

### Health

- `GET /api/v1/health`: public liveness/health projection.
- `GET /api/v1/version`: public version information.
- `GET /api/v1/status`: authenticated Runtime state.

Endpoint reachability does not prove that Kernel, models or execution isolation
are ready. Missing fields remain unknown rather than evidence of success.

### Kernel API (v1)

The `/api/v1/kernel/` family exposes the existing health, status, capability,
Provider and job adapters. These project the actual Kernel boundary; the client
cannot fabricate permits or receipts. Model inference requires the supported
Gateway/NKI path and its configured credentials. See
[execution paths](../architecture/EXECUTION_PATH.md).

### Capability

`GET /api/v1/capabilities` reads the catalog. Requests through
`POST /api/v1/capabilities/run` still pass existing admission and execution.
Use [capability availability](../operations/CAPABILITY_AVAILABILITY.md) to
interpret executor scope and prerequisites. A declared or available entry is
not an execution result.

Other useful families are `/api/v1/developer/workspace/`,
`/api/v1/workflow/`, `/api/v1/studio/extensions/` and the existing
`/api/v1/control/` human/governance surface. Their current guides are
[Studio](../operations/guides/USER_GUIDE.md),
[Workflow](../operations/guides/WORKFLOW_GUIDE.md) and
[UI extensions](STUDIO_UI_EXTENSIONS.md). Imported layouts do not invoke them.

### Trace

Read original runs and events through the existing `/api/v1/runtime/runs/`
family; the shared event reader uses its recorded cursor/sequence.
`/api/v1/traces` is a separate trace projection. Retain the original request,
Work and Run references when recovering. Missing events or a stopped HTTP wait
do not confirm backend cancellation.

Responses use the existing `ok`, `data`, `error` and optional `meta` envelope.
Inspect the returned error code and original identity. An approval wait is not
a completed mutation; UNKNOWN or a lost response does not authorize resubmission.
Historical aliases are covered by [legacy API compatibility](API_COMPATIBILITY_LEGACY.md).

## Python SDK

The beta Provider SDK reexports the canonical HTTP client:

```python
import os
from nous_provider.runtime import NousClient

runtime = NousClient(host="127.0.0.1", token=os.environ["NOUS_API_TOKEN"])
print(runtime.health())
print(runtime.status())
```

Run this against your existing authenticated service; use the client's explicit
`host` and `port` for a different endpoint. Keep the token in the configured
local environment, not source. Install the matching SDK using
[public SDK examples](../operations/getting-started/QUICK_START.md#public-sdk-examples).
[Hello Provider](../../examples/hello_provider/README.md) exercises a read-only
adapter with real signed loopback Work. It does not qualify a live model.

<a name="javascript-sdk-stub"></a>

## TypeScript HTTP client

A
[TypeScript HTTP client](../../nous_runtime/sdk/client.ts) and
[repository example](../../examples/sdk/typescript_quickstart.ts) now exist;
they are not a published stable npm package. Use the checked-in client with your
TypeScript toolchain and an authenticated service. The example's Workflow needs
its registered definition and current permission. A client method does not
supply either. No future SDK release date is promised here.

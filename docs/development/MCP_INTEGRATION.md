# Connect an MCP client

Use the stdio bridge to expose selected Runtime operations to an MCP client.

## Start the bridge

Install the `mcp` extra and start the authenticated Runtime using
[the source quick start](../operations/getting-started/QUICK_START.md). A host operator supplies
its existing service credential to the stdio bridge through
`APEIR_MCP_API_TOKEN`; never put it in a prompt, tool argument, checked-in MCP
configuration or command argument. The bridge delegates that credential only to
one host-configured Controller origin:

```bash
apeir extension serve-mcp --runtime-url http://127.0.0.1:8770
```

Remote Controller origins require HTTPS and the platform certificate trust
store. Plain HTTP is limited to numeric loopback; redirects, URL credentials,
query strings and alternate paths are rejected. The official MCP SDK owns the
stdio protocol. The bridge has a whole-call HTTP deadline and closes its request on cancellation.
It owns no execution worker, state database, approval,
trust store or verification authority. It never automatically retries HTTP calls.
The Controller authenticates every call to its existing API before dispatch.

## Configure access

All tools require an explicit current PermissionEngine rule for the authenticated
service subject, exact tool action and resource below. Missing policy fails
closed; discovering a tool does not grant it. Configure permissions through the
existing host-owned Governance policy, not through MCP or model output. The
credential remains protected bridge-process material: these rules scope MCP
calls, not every legacy API that the same service credential could access.
Exposing that credential or an unrestricted host terminal to an external agent
is not qualified by this interface.

## Available tools

| Tool | Input | Permission resource / original owner |
| --- | --- | --- |
| `apeir.nodes.list` | none | `workspace:<SHA-256 of canonical workspace path>`; existing Controller facts, never invented online state |
| `apeir.devices.inspect` | `device_id` | `device:<id>`; existing Reality DeviceRegistry |
| `apeir.work.submit` | `objective`, `idempotency_key` | workspace resource; original WorkSupervisor, read-only tool profile, maximum 8 iterations |
| `apeir.work.status` | `run_id`, optional `owner` | `work:<id>` for default `work-harness`, `distributed-work:<id>` for explicit `distributed` |
| `apeir.evidence.read` | same as status | original checkpoint/EventStream or DistributedWorkStore evidence references; never another verifier |

## Approval and recovery

Work submission additionally passes the **original** `runtime.execute` API
Governance Gate. A required human approval remains pending in the existing
approval UI/CLI; no MCP approval tool exists. An authenticated retry of the same
scoped key and identical effective inputs returns the original Run without a
new model/tool invocation or a new approval. Changed inputs, damaged bindings or
interrupted initialization fail closed. This fence is in the existing verified
checkpoint store and survives ordinary retention; it is not a new Work registry.
Missing HTTP responses or client cancellation do not imply failure of the
original Work. Query its status/evidence before any explicit recovery action.

## Limits

Results are centrally redacted and bounded to 1 MiB. Evidence exposes original
records/references; execution success, receipt, file checksum and physical MATCH
remain distinct. `owner` never falls back to another Work system. This first
interface supplies no arbitrary host command, file transfer, approval, grant or
physical operation API. A Work's own tools continue through their existing
permissions and execution boundaries. Selected-file Chat disclosure qualification
does not automatically qualify every Work Harness model-input path.

## Tests

Run the stdio/HTTP, scope, negative-security, approval and original-request
recovery contracts:

```bash
python -m pytest -q tests/extensions/test_runtime_mcp_server.py tests/work/test_work_submission.py
```

The official Codex App Server 0.163.0 was separately exercised with direct MCP
calls: thread start, tool discovery, current Node projection, original Distributed
Work query and a new Work stopped at human approval. **No model Turn ran.** This
is MCP interoperability evidence, not complete authenticated Codex Harness,
workspace-isolation, paid usage, cancellation or recovery qualification. Official
CLI authentication metadata was available, but scoped filesystem/credential and
native tool admission must be qualified before enabling a model Turn; an
instruction prompt is not that boundary.

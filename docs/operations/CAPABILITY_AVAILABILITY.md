# Capability availability

<!-- Compatibility anchors for existing documentation links. -->
<a name="capability-availability--provider-dependent-feature-degradation"></a>


Inspect which implementations the current Runtime can find and which
prerequisites are missing. Availability is a projection, not an authorization
grant, executed command, model response or verified effect.

## Overview

A capability names an operation. Its implementation may belong to the Kernel
model path, an existing Runtime service, a sandboxed command or a remote Node.
One Provider-health rule cannot establish readiness for all those scopes.

## How Availability Is Determined

The current [availability owner](../../nous_runtime/capability/availability.py)
reads enabled catalog entries and their executor metadata:

| Executor | Projection checks / limit |
| --- | --- |
| Provider | Registered Provider, health metadata and declared capability; actual inference still needs its model, credentials, Gateway/NKI and permission |
| Runtime | A supported built-in central-dispatcher implementation; marked `requires_authorization` |
| Subprocess | An immutable configured command and installed executable; marked `requires_authorization`, without proving qualified strict isolation |
| Node | Requires a bound live execution host; this legacy availability view does not itself perform Node discovery or make a remote capability ready |

Inspect the returned scope, state and reason. Health or traversal-looking
metadata is not proof that an operation actually ran. Use original execution
records and receipts for that fact.

## Viewing Availability

```bash
apeir --no-intelligence capability list
apeir --no-intelligence capability availability
```

In the documented source installation these commands reported **16 available /
53 unavailable** with models disabled. Those are environment-specific metadata
counts, not16 granted tools or successful executions. They are not a promise
about another workspace. Missing model Providers do not remove every built-in
Runtime capability.

## Degradation Paths

### Scenario: DeepSeek-only user (text-only)

A compatible endpoint may supply its actually supported text capabilities after
configuration and qualification. The vendor name does not establish vision,
audio, tool calling, authentication or model availability. Follow
[Models and Providers](guides/PROVIDER_GUIDE.md).

### Scenario: No providers configured

Model capabilities remain unconfigured/unavailable. Built-in service or installed
command metadata may still appear; admission and strict execution checks remain
independent. Source file inspection and supported pure Workflow examples can be
used without a model account.

## Integration with Capability Resolver

Execution revalidates current permission, host prerequisites, original request
and resource binding. It can be refused after discovery. A missing strict sandbox
stays BLOCKED; there is no unrestricted host fallback.

## API (Python)

Use the [public SDK/API reference](../development/API_REFERENCE.md) and
[Provider contracts](../development/PROVIDER_DEVELOPMENT.md) for integrations.
The internal availability helper is a projection implementation, not a new
public permission or invocation API.

## Design Principles

Show real state and a specific reason. Keep UNKNOWN distinct from success,
installation distinct from execution, and a receipt distinct from independent
observation. See [current boundaries](../../ROADMAP.md).

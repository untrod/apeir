# Provider Development Guide

Install the beta `nous-provider-sdk` from the matching checkout using
[Quick Start](../operations/getting-started/QUICK_START.md#public-sdk-examples);
this guide does not claim a published stable package. Import Distribution contracts from
`nous_provider.runtime`, conformance from `nous_provider.conformance`, and legacy
Kernel NPA interfaces from `nous_provider`. The SDK forwards to authoritative
implementations; third-party packages do not import internal Runtime modules.
See [Developer Platform](DEVELOPER_PLATFORM.md) for the M3.6 audit and packaging.

## Runtime model adapter

```python
from nous_provider.runtime import ProviderAdapter, ProviderManifest

class FixtureIntelligence(ProviderAdapter):
    @property
    def manifest(self):
        return ProviderManifest(
            provider_id="fixture.intelligence", provider_name="Fixture",
            capabilities=["model.reason"], requires_credential=False,
        )

    def invoke(self, capability_id, **params):
        if capability_id != "model.reason":
            return {"ok": False, "error": "unsupported capability"}
        return {"ok": True, "content": "deterministic fixture output"}

    def health(self):
        return {"status": "ok"}
```

This is a fake intelligence fixture, not a validated external model integration.
The host registers adapters through its existing Provider service. An adapter's
`invoke` is an execution-boundary callback, not an application authorization API.
Discovery and declared capabilities never confer trust or authority.

## Devices and Nodes

Use `DeviceProvider`, `DeviceDiscovery`, `DeviceTransport`, and `ManagedDevice`
for Reality discovery and independent state observation. Device transport locators
are routes, not identity; rediscovery cannot revive REVOKED resources. Use
`NodeRuntimeConfig`, `NodeRuntimeService`, `NodeProtocolEnvelope`, and
`DistributedWork` for existing Node/Work contracts. A Node executes assigned
Work; a Device is the resource affected or observed. They are not interchangeable.

Device mutation belongs to the existing governed Operation handler, Distributed
Work admission and Node execution path. Providers must not call the device directly
from an Agent or treat a scheduling assignment as authority. Receive credentials
only through the existing current-Operation CredentialContext at that boundary.
Never resolve secrets into prompts, plans, receipts, observations or logs.

## Contract conformance

```python
from nous_provider.conformance import (
    CTKRunner, RuntimeConformanceTarget, register_runtime_suites,
)

runner = CTKRunner()
register_runtime_suites(runner, RuntimeConformanceTarget())
report = runner.report_json(runner.run_required(["runtime-node", "runtime-device"]))
```

An empty target reports SKIP, not successful validation. Supply canonical records
from a controlled governed run to test actual contracts. Metadata probes never
invoke a Provider. Execution evidence requires the same Work/Operation identity,
its Receipt, independent fresh Observations and an independently recomputed MATCH.
UNKNOWN and MISMATCH fail closed. Repeating conformance does not replay an effect.

The legacy Provider conformance helper requires an explicit governed execution
probe for invocation tests; `invoke(test_mode=True)` is not a safety boundary.
Contract certification does not prove native ABI execution, physical behavior,
production identity, performance or recovery for an unexercised provider.

## Compatibility and packaging

The Provider SDK is beta (`1.0.0b2`), installed from the matching Distribution
checkout. Its public imports forward canonical Runtime contracts; they do not
create a separate execution service. Keep the source revision and dependency
lock with your adapter's tests. The package's broad beta dependency range is
not a promise that every future prerelease has an identical Python API.

For Studio-only panels, use the versioned [UI contract](STUDIO_UI_EXTENSIONS.md)
and its advertised host features. The standard-library example requires no
Provider SDK installation. An existing v1 status widget remains compatible;
new Workflow data requires explicit host support and original resource admission.

Develop packages in their own repository. Include a manifest, license, supported
host/profile requirements and a bounded read-only example. Validate against the
public SDK and appropriate conformance target, then exercise the real governed
consumer. Report installation, execution, isolation and physical verification
separately. A package checksum or a passing metadata probe cannot replace them.

# Write a Provider

Build a read-only adapter through the public beta SDK, then let the existing
trusted host admit its Work. Start from the already runnable
[Hello Provider](../../examples/hello_provider/README.md), not an internal
`nous_core` registration hook.

## 3 Methods

The existing example supplies discovery/manifest, `invoke` and `health` through
`Provider` and `ProviderAdapter` from `nous_provider.runtime`. Its adapter returns
`Hello, Developer!`; the host separately supplies policy, signed loopback Node
Work, CAS evidence and admission checks. The Provider receives input, not an
approval context or credential store.

Read [Provider Development](PROVIDER_DEVELOPMENT.md) for the public interface.
Copy the example outside the checkout, install the matching SDK as described in
[Quick Start](../operations/getting-started/QUICK_START.md#public-sdk-examples),
then run its fixed read-only host in a dedicated workspace:

```bash
python run_example.py --workspace ./provider-demo
```

Expected: COMMITTED read-only Work and a greeting, with signed receipt and CAS
references. Unknown capability, missing permission and mutation examples must
remain denied, UNKNOWN or awaiting approval. This is not a cloud model test or
physical-device acceptance.

## Register

The example's trusted host uses the existing ProviderRegistry and independently
checks the bound request before invocation. A third-party adapter does not call
a global function to grant its own permissions. Production integration reuses
that same authority and current execution boundary.

## Risk Levels

Declare the actual capability, credential/network needs and risk honestly.
The declaration is input to review, not an authorization grant. Side effects
require their existing Operation, approval, execution and verification path.

## Test with Demo Mode

Use the fixed [Verified Execution Demo](../../examples/hello_runtime/README.md)
for simulated mutation, independent observation and no-replay recovery. It is
separate from this read-only adapter; deterministic output is not proof of live
model availability.

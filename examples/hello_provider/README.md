# Hello Provider

A credential-free, read-only adapter using the public Provider SDK. Install
Distribution and the SDK using the [Source Quick Start](../../docs/operations/getting-started/QUICK_START.md#public-sdk-examples), then run from the checkout:

```bash
python examples/hello_provider/run_example.py --workspace ./provider-demo
```

Use an empty dedicated directory. `hello_provider.py` declares `example.greet`
and returns a greeting; it imports no internal Runtime modules and receives no
authority, credential store or Governance context. `run_example.py` is the
trusted local host: it installs the adapter in the existing ProviderRegistry,
defines an explicit read-only policy, submits the original Distributed Work,
and revalidates its authorization and Node binding immediately before invocation.
The signed loopback Node protocol transfers the CAS input and returns real
execution evidence. No arbitrary code sandbox or physical-device qualification
is claimed for this fixed in-process read-only handler.

The JSON output contains the COMMITTED read-only Work, greeting, signed receipt,
CAS references, existing governance audit and two target-backed CTK contract
probes. Unknown capabilities are DENY, missing permissions UNKNOWN, and a
firmware mutation request REQUIRE_APPROVAL; none of those requests executes.
Removal unregisters only capabilities still owned by this Provider and prevents
further host admission. Provider errors map to FAILED Work in the negative test.

COMMITTED here concerns a read-only result. For an actual simulated mutation,
independent Observation and MATCH-only EffectVerification, use the
[Verified Execution Demo](../hello_runtime/README.md).
State is retained under the printed workspace. Do not publish its private Node
keys or databases. Never put credentials in a Provider manifest or ordinary
Work; protected execution-time credentials use the existing CredentialBroker.

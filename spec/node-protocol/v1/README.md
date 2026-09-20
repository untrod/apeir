# Nous Node Protocol v1

The protocol owns Nous node semantics and uses a mature WebSocket transport.
Plain `ws://` is restricted to loopback testing; remote nodes require `wss://`
with normal certificate and hostname validation.

Every envelope is deterministic JSON signed with the sender's durable Ed25519
identity. Receivers enforce a 1 MiB message limit, protocol negotiation,
timestamps, monotonic sequence numbers, duplicate message rejection, explicit
timeouts, and idempotency keys for replayable operations.

Message types are: REGISTER, HEARTBEAT, RESOURCE_REPORT, WORKLOAD_START,
WORKLOAD_STOP, WORKLOAD_STATUS, LEASE_ACQUIRE, LEASE_RELEASE, ARTIFACT_FETCH,
ARTIFACT_READY, DEVICE_REPORT, TELEMETRY, ERROR, and ACK.

Implemented end-to-end in R2: registration, acknowledgements, heartbeat,
resource/device/telemetry reports, workload start and workload status. Workload
stop, leases and artifact transfer are reserved with fail-closed responses until
their owning runtime mechanisms are implemented; defining a message does not
grant authority or imply successful execution.

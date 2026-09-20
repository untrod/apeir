# Nous Foundation system map

This is the canonical high-level map. Detailed compatibility contracts are in
`spec/contracts/v1`.

```text
Products and adapters
Desktop | CLI | Python SDK | Rust SDK | C SDK | ROS 2 | OPC UA | OpenClaw
                              |
                              v
                    NKI and Provider ABI
                              |
                              v
  +-----------------------------------------------------------+
  | Nous execution kernel                                     |
  |                                                           |
  | Execution -> Safety -> Admission -> Scheduler Core        |
  |      |                                  |                 |
  |      v                                  v                 |
  | State Journal <-> Semantic State     Resource Lease       |
  |      |                                                    |
  |      v                                                    |
  | Evidence-backed Knowledge -> Transactional Effects        |
  |                                  |                        |
  |                         Credential Broker                 |
  |                                  |                        |
  |                         Provider / Device                 |
  +-----------------------------------------------------------+
                              ^
                              |
        governed learning proposes policy; safety can reject
```

## Runtime profiles

| Profile | Purpose | Durable journal | Distributed scheduling | Learning |
|---|---|---:|---:|---:|
| Core | server and workstation kernel | yes | yes | governed |
| Edge | local device or gateway | yes | no | evaluation only |
| Micro | MCU and RTOS target | host-mediated | no | no |

All profiles retain transactional effects and a safety boundary. Feature absence
never permits a profile to bypass a contract.

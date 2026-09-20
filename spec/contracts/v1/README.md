# Nous Foundation external contracts v1

This directory is the compatibility boundary for the Nous execution kernel.
The ten contracts below are frozen at version 1. Additive fields must remain
optional. Removing a field, changing its meaning, or weakening a safety rule
requires a new major contract version.

| ID | Contract | Authority | Existing representation |
|---|---|---|---|
| NEC | Nous Execution Contract | `nousd` | Workload IR and execution lifecycle |
| NSO | Nous State Ownership | `nous-state` journal | journal, CAS generation and fencing |
| NTE | Nous Transactional Effects | effect engine | intent, authorization, receipt and commit |
| NRP | Nous Resource Protocol | scheduler core | resource claim, placement and lease |
| NPA | Nous Provider ABI | provider host | Engine ABI, Device ABI and Provider SDK |
| NKI | Nous Kernel Interface | NKI server | `spec/nki/v1/nki.proto` |
| NMP | Nous Micro Protocol | Nous Micro | fixed-size `nous_nmp_frame_v1` |
| NCT | Nous Credential Contract | credential broker | reference and scoped lease only |
| NLC | Nous Learning Contract | learning governance | draft, shadow, verification, canary, active |
| NSE | Nous Safety Envelope | safety gate | immutable hard constraints and safe fallback |

## Required order

Every production execution follows this order:

`NKI -> NEC validation -> NSE -> NRP admission and scheduling -> NSO intent -> execution -> NTE -> NSO commit -> result`

Learning may propose scheduler or routing policy changes through NLC. It cannot
modify NKI, state ownership, credentials, approval rules, or the safety envelope.
An NSE rejection always overrides an NLC approval.

## Runtime profiles

- Core implements all contracts and durable/distributed operation.
- Edge implements the same wire contracts with local scheduling and durable state.
- Micro implements NEC, NTE, NMP, NCT and NSE with fixed memory and no dynamic allocation.

The Rust registry in `nous-types::FOUNDATION_CONTRACTS` and the C header
`sdk/c/include/nous_kernel.h` are machine-readable mirrors of this document.

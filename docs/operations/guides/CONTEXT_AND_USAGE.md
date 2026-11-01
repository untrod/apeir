# Inspect context, Tokens and cost

Check what the application selected, what the Provider reported and which
statistics remain unknown. These are different records; an input manifest is
not a delivery receipt, and cached Tokens are not a money-saving measurement.

## Inspecting actual model input

Choose **Inspect model input** on a response or **Inspect active input** during a
request. **Recorded model input** opens a prior Run after restart without another
model call. Conversation, Run and Trace IDs keep their separate meanings.

The persisted content-free manifest records roles, counts, digests, tool
declarations, selected/omitted context and preceding tool-result metadata. A
successful file read identifies its relative source, selected lines and digest
from the same bytes. File text and tool arguments are not duplicated into these
metadata events. Failed reads are not reported as successful access.

A saved Workspace reference selects a path/SHA-256. **Send** requests a current
bounded read and separate Provider-transfer admission; selection alone sends no
bytes. Safe reading, current versions and permissions are rechecked at actual
Gateway attempts. Revocation blocks later transfer, though already sent bytes
cannot be recalled. Default configuration grants no sharing permission. Use the
host-owned [context permission policy](../configuration/CONFIG_REFERENCE.md#context-permission-policy);
Windows requires its same-handle owner/protected-DACL contract. Unsupported safe
readers remain BLOCKED.

The manifest describes **application Gateway input**, not the Provider's final
HTTP envelope or proof of receipt. It is bounded to 256 messages, 64 tools and 128
sources; complete counts/digest remain available. The inspector reads at most
1,600 events with explicit truncation. Missing/legacy events stay UNKNOWN.
Collaborative worker/reviewer inputs are not covered by this Chat manifest.

The archived conversation excerpt is untrusted, incomplete history, not a
semantic summary or permission. Context snapshots preserve source/version,
owner, digests and omission reasons. Required objectives, plans and governance
items stay whole; an insufficient budget blocks dispatch. Work Harness separately
bounds prepared JSON to 96,000 characters and pauses before dispatch rather than
cutting a goal in half. Character and Token estimates are not measured usage.
Incremental snapshot APIs exist, but do not establish a qualified incremental
project-cache path throughout Chat.

Raw attachment/drop/paste delivery and Chat Node/privacy/per-request-budget
controls are unavailable in this path and are refused without clearing the
draft. Use admitted saved-file references. Configure the existing Provider and
budget policy before sending; disabled controls must not silently ignore input.

## Model usage and cost

**Model Lab / Usage** and the status bar read the same CostController journal via
`GET /api/v1/usage`. Change the UTC day and inspect original request/attempt/
receipt references. Controller changes clear old pending reads and billing data.
Reported, derived, estimated and unknown values, cache counters, pending requests
and reservations remain distinct. Missing usage/cost is UNKNOWN, not zero.
Reported usage is telemetry, not an independently verified invoice.

Budgets reserve before dispatch. A timeout/cancellation does not prove a request
was free, and cancellation cannot undo an already admitted charge. Parallel
children retain their own parent bindings, deadlines and unsettled accounting;
a missing response does not permit a new fan-out. A child cancellation is not
automatically parent cancellation. Positive aggregate limits cannot undo charges
from concurrent requests already dispatched.

**What reduces avoidable work today:** bounded context selection, deterministic
tool reads, one path for ordinary code/test requests and bounded archived-excerpt
loading. **What has not been demonstrated:** a general Token-saving percentage,
a real-model twenty-task cost comparison or complete semantic long-task
compression. Exact model choice stays locked; cheaper is not a substitute for
correct. See [measured scope](../../acceptance/ENGINEERING_REVIEW.md#developer-intent-and-model-selection-correction--2026-10-27).

Pricing uses the existing host-selected `APEIR_MODEL_PRICING_FILE`. Unknown
prices stay unknown. Token-only policy requires both existing
`APEIR_MAX_DAILY_COST_USD` and `APEIR_MAX_RETRY_COST_USD` to be `none`; this read
view never changes policy or invents a vendor billing cap.


# Nous Kernel — Breaking Changes Log

> Track all breaking changes across versions for migration planning.

## RC4 (current)

### 2026-08-04: NKIOutcome tagged enum

- **Change:** NKI response envelope changed from `#[serde(untagged)]` to `#[serde(tag = "status")]`
- **Before:**
  ```json
  {"request_id": "...", "payload": {...}}
  // or
  {"request_id": "...", "error": {"code": "...", "message": "..."}}
  ```
- **After:**
  ```json
  {"request_id": "...", "status": "success", "payload": {...}}
  // or
  {"request_id": "...", "status": "error", "error": {"code": "...", "message": "..."}}
  ```
- **Affected:** All NKI clients (Python, Rust, future C/JS clients)
- **Migration:**
  - Python: `if "error" in response` → `if response.get("status") == "error"`
  - Rust: No code change needed (pattern match on enum, serde handles tag)
- **Reason:** Untagged enum is fragile — if NKIErrorBody ever adds a `payload` field, serde would match Success first and ignore the error. Tagged enums are unambiguous and future-proof.

### 2026-08-04: DeviceStatus power field renamed

- **Change:** `DeviceStatus.power_watts: u32` → `DeviceStatus.power_milliwatts: u64`
- **Reason:** Consistency with `ResourceVector.power_milliwatts: u64`
- **Migration:** Update JSON keys from `power_watts` to `power_milliwatts`; values must be multiplied by 1000 if previously in watts.

### 2026-08-04: Deadline enforcement in AdmissionController

- **Change:** Workloads with `deadline_us` in the past are now rejected at admission (previously silently accepted)
- **Affected:** Clients sending workloads with absolute deadlines
- **Migration:** Ensure `deadline_us` is set to a future timestamp (0 = no deadline)

### 2026-08-04: WorkloadPhase display format

- **Change:** `WorkloadType` now uses `Display` trait for serialization (was `Debug` format)
- **Impact:** No functional change — both produce the same output for this enum. Internal change only.

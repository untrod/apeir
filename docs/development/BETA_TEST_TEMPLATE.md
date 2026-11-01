# Developer Preview feedback template

<!-- Compatibility anchors for existing documentation links. -->
<a name="beta-test-template"></a>


## Tester Info

- Date, OS/architecture and Python version:
- Distribution/source SHA and artifact identity:
- Kernel/component-lock identity, if native components are involved:
- Path: Source Preview / Windows development build / Developer Setup:

Do not attach credentials, private Runtime databases, device keys or raw personal
project content. Use [SECURITY](../../SECURITY.md) for private vulnerabilities.

## Tasks

Record PASS, PARTIAL, PENDING, BLOCKED or FAIL for each attempted task. Keep the
actual error and original Work/Run identity; do not resubmit uncertain effects
just to obtain another result.

### 1. Installation

- [ ] Follow the matching [Quick Start](../operations/getting-started/QUICK_START.md).
- [ ] Verify file SHA-256/source manifest where provided.
- [ ] Run `apeir version` from the intended environment.
- Actual result / time / issue:

### 2. First Run

- [ ] Start the model-free Runtime and connect Studio through Quick Start.
- [ ] Inspect Runtime, Kernel and model configuration states.
- [ ] Open a project file; save and restore a presentation layout.
- Actual result / original references / issue:

### 3. Provider Setup

- [ ] Configure a supported protocol and credential reference.
- [ ] Distinguish configuration, reachability and inference.
- [ ] Test a model only with the account owner's consent and explicit budget.
- Actual result / original request / Usage source / pending prerequisites:

### 4. Demo

- [ ] Run [Hello Workflow](../../examples/hello_workflow/README.md), inspect its
  original Run and repeat the same key without creating another run.
- [ ] Run the [simulated Demo](../../examples/hello_runtime/README.md) if needed;
  label it simulated and check its independent observation/effect count.
- Actual result / recovery record / issue:

### 5. Pack

- [ ] Use a [supported example](../../examples/README.md) for the chosen extension.
- [ ] Distinguish installed, enabled, authorized and actually executed states.
- [ ] Check refusal/removal, not only success metadata.
- Actual example / result / limitation:

### 6. Overall

- Total time:
- First confusing instruction or missing prerequisite:
- Could you find the original task, error and evidence?
- Which supported task would you use again?
- Unperformed items and why:

Windows GUI/install/upgrade/uninstall/Defender checks need the actual target
Windows host. Source-browser results do not fill those rows. Test old workspace
migration only after backup and in an isolated copy.

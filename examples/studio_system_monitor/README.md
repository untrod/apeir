# System Monitor UI extension

A data-only third-party Panel and Widget using the public
[`apeir.studio-ui/v1` contract](../../spec/extensions/v1/studio-ui.schema.json).
No Runtime imports, JavaScript, external URLs, Shell or model account are needed.
This example is an unverified publisher claim, not a trusted signature.

Start the model-disabled local Runtime and Studio using the official
[Quick Start](../../docs/operations/getting-started/QUICK_START.md).
Copy this directory outside the checkout to work on your own extension.

In Studio, **Add panel → UI Extensions → Review manifest**, select
`nous.extension.json`, review the identity, SHA-256 and permission requests,
then **Request install**. A pending request is not an installation. Use the
existing authenticated human approval surface, or the local owner's CLI:

```bash
apeir approval list --json
apeir approval approve ORIGINAL_REQUEST_ID
```

Return to the original request and submit it once with its original binding.
The package starts disabled. **Enable** is a separate governed operation.
Enablement permits the declared sanitized read interface under current host
policy; it grants no executable tools or device permissions.

Add **System Monitor** from the Panel library. In layout edit mode, add
**Runtime Monitor** from the Dashboard Widget list. Save the existing Studio
layout normally. Its component type is stable across package versions. Layouts
contain presentation only, never the package's grant, token or live status.

The sample shows actual Runtime status and bounded current-session samples of
pending jobs. Registered providers/capabilities are counts, not proof of their
availability. Kernel state may be UNCONFIGURED/BLOCKED. Missing values stay
UNKNOWN; these reads are not independent physical observations. Lifecycle reads
return bounded existing EventBus metadata, not raw payloads or a new event bus.

The standard-library client can run from the copied directory without installing
or importing APEIR there. Supply the existing token through your shell's
`NOUS_API_TOKEN` environment variable. Never commit or print it.

```bash
python monitor_client.py review
python monitor_client.py install
python monitor_client.py list
python monitor_client.py enable
python monitor_client.py read
python monitor_client.py events
python monitor_client.py disable
python monitor_client.py remove
```

The client does not approve or automatically retry mutations. Pending requests
exit with their original approval ID. After a separate approval, repeat only the
same reviewed command. A transport error requires inspection of original Registry
or Run state before deciding whether another request is safe. Non-loopback
endpoints require HTTPS; redirects are rejected rather than forwarding credentials.

To update, change `version`, review the new file and request installation again.
Replacing the same version with different bytes is rejected. Updates start
disabled. Disablement immediately denies new component reads/actions; uninstall
leaves inert **Missing Extension** slots, preserving the Dashboard layout.

The host validates the child Schema plus bounds, duplicate IDs, dependency
compatibility and action uniqueness. Dependencies must already be installed;
this importer does not download them. A single optional `workflow.run` action
can reference an immutable registered definition and explicit execute request.
It still needs current host permission, the existing Gate and an original
idempotency key. Only the bound pure Workflow handler profile is available.
Host command, device, model and external side-effect handlers are BLOCKED here.
Arbitrary executable third-party UI remains BLOCKED pending isolation qualification.

The public API and versioned contribution types are described in the existing
[Developer Platform guide](../../docs/development/DEVELOPER_PLATFORM.md#declarative-ui-extension-sdk).

## Workflow Monitor

Use `workflow-monitor.extension.json` for a read-only Workflow Panel and Widget.
It shares this directory's client; copy both files outside the checkout. It
requires a host advertising `data.workflow.summary` and the current user's
Workflow read permission. An older native build can support System Monitor
without supporting this newer feature. Check the host before installing.

Create a pure Workflow in the Runtime's selected project using the existing
[Hello Workflow](../hello_workflow/README.md) commands. No model, Shell or device
operation is needed. From the copied extension directory, with the existing API
token in `NOUS_API_TOKEN`:

```bash
python monitor_client.py contract
python monitor_client.py review --manifest workflow-monitor.extension.json
python monitor_client.py install --manifest workflow-monitor.extension.json
# Independently approve the original request with the existing owner CLI.
# Continue only that same request after approval, then separately enable it.
python monitor_client.py enable --manifest workflow-monitor.extension.json
python monitor_client.py read --manifest workflow-monitor.extension.json
python monitor_client.py disable --manifest workflow-monitor.extension.json
python monitor_client.py remove --manifest workflow-monitor.extension.json
```

Each mutation can require its own original approval. The client does not approve
itself or retry after a lost response. `--manifest` selects the package identity;
`read` selects its declared data source. `--extension-id` and `--source` can
explicitly select them when needed. Supply `--endpoint` if the Runtime uses a
different origin.

In Studio, install the same reviewed manifest, enable it, then add **Workflow
Monitor** as a Panel or **Workflow Summary** as a Dashboard Widget. The displayed
window is the latest 100 recorded runs in this workspace. `unknown_runs` is
separate from `completed_runs`; unavailable data is not zero. No Run IDs, names,
inputs, results or credentials enter this projection. Completing a Workflow is
not proof of a physical effect or a successful project test.

Updates use a new immutable version and start disabled. Saved layouts keep the
same component IDs. Restart reads the original history; merely opening a Widget
never submits another Workflow. See the [SDK contract](../../docs/development/STUDIO_UI_EXTENSIONS.md#host-compatibility)
for compatibility and resource-permission requirements.

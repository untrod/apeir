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

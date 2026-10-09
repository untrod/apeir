# Container installation boundary

The recommended Developer Preview path is the [source Quick Start](QUICK_START.md).
No public APEIR container image is qualified by this source preview.

The root Dockerfile builds historical `remote_terminal`, not the current
governed Runtime. It is retained for compatibility and history; it is not
evidence of a current Controller, Console or Verified Demo deployment.
The previously documented Compose installation and `nous-runtime/nous:latest`
release image are not supplied by this repository.

For Node/Controller deployment follow the
[Compute Mesh runbook](../compute-mesh/OPERATIONS.md). Development containers
running lifecycle tests need an init/reaper and writable temporary storage;
see the [supported environment](../../development/DEVELOPER_PLATFORM.md#supported-development-environment).
Release images require the [Release Runbook](../../acceptance/RELEASE_RUNBOOK.md).

# User Guide

The task-oriented [Studio guide](guides/USER_GUIDE.md) is the current user manual.
This page keeps existing links usable without maintaining a second set of setup
commands.

## First checks

Use [Quick Start](getting-started/QUICK_START.md#first-inspection) for model-free
inspection and actual Runtime connection status.

## Workspaces

[Open and review project files](guides/USER_GUIDE.md#reviewing-workspace-changes).
The selected workspace owns its state. Back up the whole workspace before
migration; do not copy private credentials into a CI environment.

## Providers and models

[Configure a Provider](guides/PROVIDER_GUIDE.md). A saved profile or health probe
is not inference qualification.

## Tasks and interaction

[Run a supported Workflow](guides/WORKFLOW_GUIDE.md) and inspect its original
records. [Context and Usage](guides/CONTEXT_AND_USAGE.md) explains the selected
input and accounting views.

## Local Control Plane

For persistent Controller/Node services use the
[Compute Mesh runbook](compute-mesh/OPERATIONS.md). The first-run Studio path
uses the authenticated local Runtime API from Quick Start; remote deployment
has additional identity, TLS, network and permission requirements.

## Troubleshooting

Use [Troubleshooting](getting-started/TROUBLESHOOTING.md) and
[CLI reference](../development/CLI_REFERENCE.md). Report sanitized steps and
version/source identity, not private Runtime databases or credentials.

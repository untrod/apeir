# Developer guide / 开发者指南

Start with a working checkout from [Quick Start](../operations/getting-started/QUICK_START.md#developer-setup).
This page helps you find the interface you need and the code that implements it.

APEIR is the platform. **Studio** is the workspace, **Runtime** handles execution
and permissions, and **Kernel** is the separately maintained execution component.

## Studio

<a name="surfaces"></a>
<a name="apeir-studio"></a>
<a name="overview--概览"></a>
<a name="watching-a-request"></a>
<a name="reviewing-workspace-changes"></a>
<a name="professional-workbench"></a>
<a name="interactive-project-execution"></a>

Use the existing panel registry, layout library and design tokens when extending
the interface. Layout configuration describes presentation; task state stays in
the Runtime.

- [Studio guide](../operations/guides/USER_GUIDE.md): navigation, panels and saved layouts.
- [Project changes](../operations/guides/USER_GUIDE.md#reviewing-workspace-changes): editor, diffs and approval.
- [Task activity](../operations/guides/USER_GUIDE.md#watching-a-request): requests, tools and results.
- [Project tests](../operations/guides/USER_GUIDE.md#professional-workbench): the governed test profile and its environment requirements.

## Models and Providers

<a name="first-use-configuration-and-model-tests"></a>
<a name="inspecting-actual-model-input"></a>
<a name="model-usage-and-cost"></a>
<a name="model-evidence"></a>

Use [Models and Providers](../operations/guides/PROVIDER_GUIDE.md) to connect an
existing service. Local and cloud profiles can coexist. To implement an adapter,
use the [Provider SDK](PROVIDER_DEVELOPMENT.md) and [Hello Provider](../../examples/hello_provider/README.md).
Model requests use the existing Gateway; an adapter supplies an implementation,
not approval for its own operations.

[Context and Usage](../operations/guides/CONTEXT_AND_USAGE.md) explains selected
files, model input, Tokens and cost. Unreported usage remains unknown.

## Workflow

<a name="visual-workflow-builder"></a>

The visual editor and CLI use the same `WorkflowDefinition` and Runtime.
Start with [Hello Workflow](../../examples/hello_workflow/README.md), then use the
[Workflow guide](../operations/guides/WORKFLOW_GUIDE.md) for supported handlers,
data bindings, approval and recovery. Keep canvas coordinates out of execution
parameters.

## Extensions

<a name="declarative-ui-extension-sdk"></a>

[UI Extension SDK](STUDIO_UI_EXTENSIONS.md) documents declarative panels and
widgets. Copy [System Monitor](../../examples/studio_system_monitor/README.md)
into a separate project to develop against the public contract. The host renders
these contributions; arbitrary third-party JavaScript is not enabled.

### Skills and tools

Use **Operations Console → Skills** to review a local or supported HTTPS package,
then install, load or enable it. Source, version, digest and requested
capabilities are shown before installation. Follow
[Hello Skill](../../examples/hello_skill/README.md) for a local catalog example.

An instruction Skill supplies text. Executable tools need a supported handler
and execution permission. Installing a package does not grant either.
[Extension formats](ECOSYSTEM.md) covers the available integration paths.

## SDK

<a name="m36-public-runtime-sdk-audit"></a>
<a name="source-sdk-onboarding"></a>
<a name="packaging-and-compatibility"></a>
<a name="conformance-evidence"></a>

Install the matching SDK from your checkout:

```bash
python -m pip install -e sdk/provider/python
python examples/hello_provider/run_example.py --workspace ./provider-demo
```

The Python beta SDK exports public contracts from `nous_provider.runtime`.
Controller, Node and CLI belong to `apeir-distribution`; existing `nous`,
`nous_runtime` and `NOUS_*` names remain compatible. See
[Compatibility](COMPATIBILITY_MATRIX.md) before changing a public interface.

### MCP access to the existing Runtime

Connect an MCP client through the [MCP integration guide](MCP_INTEGRATION.md).
It covers the stdio bridge, authentication, permission policy and original-task
recovery. The bridge exposes existing Runtime operations rather than a separate
executor.

## Examples and code navigation

[Examples](../../examples/README.md) lists prerequisites and runnable commands.
The [code map](RUNTIME_MODULE_MAP.md#current-code-entry-points) locates the CLI,
API, Gateway, Workflow, Governance, Work, Evidence, Node/Mesh, Studio and SDK.

## Development and tests

<a name="ci-scope-and-measured-cost"></a>
<a name="supported-development-environment"></a>

Use an executable CPython interpreter, writable checkout and temporary storage,
a named user and a resolvable hostname. Linux containers running process lifecycle
tests need `--init` or an equivalent reaper. Keep `HOME` unchanged; use
`NOUS_WORKSPACE_ROOT` when a test requires a separate workspace.

Install development dependencies and follow the checks in
[CONTRIBUTING](../../CONTRIBUTING.md). For Studio:

```bash
cd desktop
npm run typecheck
npm run lint
npm test
npx playwright install --with-deps chromium
npm run test:e2e
```

`APEIR_TEST_PYTHON` selects the interpreter for browser tests. Those tests start
their own model-free Runtime processes; native installation has a separate
[release runbook](../acceptance/RELEASE_RUNBOOK.md).

<a name="scheduling-boundary"></a>
<a name="experiment-evidence"></a>
<a name="current-boundary"></a>
<a name="m36-validation-record"></a>
<a name="canonical-work-read-correction"></a>

## Reference

[HTTP API](API_REFERENCE.md) · [CLI](CLI_REFERENCE.md) ·
[Provider SDK](PROVIDER_DEVELOPMENT.md) · [Extension schemas](../../spec/extensions/v1/README.md)

For execution or permission changes, read the [architecture contracts](../architecture/README.md),
including [state ownership and recovery](../architecture/STATE_OWNERSHIP.md#failure-and-recovery).
[ROADMAP](../../ROADMAP.md) tracks current status;
[Engineering Review](../acceptance/ENGINEERING_REVIEW.md) retains dated tests,
build records and historical SDK audits.

# Extensions and integration paths

<!-- Compatibility anchors for existing documentation links. -->
<a name="apeir-developer-ecosystem"></a>


Choose the smallest existing interface that fits the task. The preview provides
examples and beta contracts; it does not claim an established public marketplace
or a stable universal SDK.

## Getting Started

| Integration | Guide | Runnable example |
| --- | --- | --- |
| Provider adapter | [Provider SDK](PROVIDER_DEVELOPMENT.md) | [Hello Provider](../../examples/hello_provider/README.md) |
| Instruction Skill | [Skills](DEVELOPER_PLATFORM.md#skills-and-tools) | [Hello Skill](../../examples/hello_skill/README.md) |
| Declarative Studio UI | [UI Extension SDK](STUDIO_UI_EXTENSIONS.md) | [System Monitor](../../examples/studio_system_monitor/README.md) |
| Supported Workflow | [Workflow guide](../operations/guides/WORKFLOW_GUIDE.md) | [Hello Workflow](../../examples/hello_workflow/README.md) |

Follow [Quick Start](../operations/getting-started/QUICK_START.md) for the matching
Runtime/SDK. Keep package source, versions, digests and tested scope with the
result. Avoid private Runtime imports in third-party adapters.

## Pack Registry (Concept)

Public Pack search/publishing is not an exercised service. No `pack publish`
command or future release date is promised here. Current local package handling
is described in [Pack development](PACK_DEVELOPMENT.md).

## Pack Templates

Start with a reviewed existing package and the actual manifest parser. Legacy
scaffold output is not proof that an entry point works with the public SDK or
that execution is isolated.

## Development Workflow

Copy a supported example → review its manifest → implement the narrow adapter
or presentation → test success and refusal → inspect original evidence → submit
a scoped PR. Installation, enablement, permission and execution are separate.

## Community

Use [Issues](https://github.com/untrod/apeir/issues) for sanitized reproductions
and proposals. Architecture, examples and contributor requirements are indexed
in [Documentation](../README.md). No separate support chat or response SLA is
claimed here.

## Contributing

[CONTRIBUTING](../../CONTRIBUTING.md) owns setup, code style, checks and protected
PR integration. [SECURITY](../../SECURITY.md) owns private vulnerability reporting.

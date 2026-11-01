# Development

Choose an interface or a task before reading Runtime internals.
[CONTRIBUTING](../../CONTRIBUTING.md) owns environment, code style, targeted checks
and protected-main PR integration.

## Start here

- [Developer Setup](../operations/getting-started/QUICK_START.md#developer-setup)
- [Developer Platform](DEVELOPER_PLATFORM.md): public surfaces and compatibility
- [Runnable examples](../../examples/README.md)
- [Models and Providers](../operations/guides/PROVIDER_GUIDE.md)
- [Workflow guide](../operations/guides/WORKFLOW_GUIDE.md)
- [UI Extension SDK](STUDIO_UI_EXTENSIONS.md) and [System Monitor](../../examples/studio_system_monitor/README.md)

## Reference

[HTTP API](API_REFERENCE.md) · [CLI](CLI_REFERENCE.md) ·
[Provider SDK](PROVIDER_DEVELOPMENT.md) · [Write a Provider](WRITE_A_PROVIDER.md) ·
[Pack development](PACK_DEVELOPMENT.md) · [Extension paths](ECOSYSTEM.md)

The Python Provider SDK is beta and installed from the matching source checkout.
The checked-in TypeScript HTTP client is not a published stable npm package.
[Runtime module map](RUNTIME_MODULE_MAP.md) explains repository structure;
[Write a Module](WRITE_A_MODULE.md) helps choose a supported extension boundary.

## Compatibility and decisions

[Compatibility matrix](COMPATIBILITY_MATRIX.md) · [Deprecation](DEPRECATION_POLICY.md) ·
[Legacy names](LEGACY_COMPATIBILITY.md) · [Version policy](VERSIONING_POLICY.md) ·
[Project governance](GOVERNANCE.md)

[Canonical architecture](../architecture/README.md) and
[Engineering Review](../acceptance/ENGINEERING_REVIEW.md) retain authority and
acceptance detail. Old names and dated examples are not promises of a current
release, live Provider, native installation or physical effect.

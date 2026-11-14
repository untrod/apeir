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

[MCP integration](MCP_INTEGRATION.md) covers client access to existing Runtime tools.

The Python Provider SDK is beta and installed from the matching source checkout.
The checked-in TypeScript HTTP client is not a published stable npm package.
[Current code entry points](RUNTIME_MODULE_MAP.md#current-code-entry-points) map the maintained owners;
[Write a Module](WRITE_A_MODULE.md) helps choose a supported extension boundary.

## Compatibility and decisions

[Compatibility matrix](COMPATIBILITY_MATRIX.md) · [Deprecation](DEPRECATION_POLICY.md) ·
[Legacy names](LEGACY_COMPATIBILITY.md) · [Version policy](VERSIONING_POLICY.md) ·
[Project governance](GOVERNANCE.md)

[Canonical architecture](../architecture/README.md) and
[Engineering Review](../acceptance/ENGINEERING_REVIEW.md) retain authority and
acceptance detail.

## Run the checks for your change

Install the development dependencies using [CONTRIBUTING](../../CONTRIBUTING.md).
From the checkout, a documentation change starts with:

```bash
python scripts/markdown_link_check.py
python -m pytest -q tests/repository tests/test_open_source_hygiene.py
```

For a Provider or example change, run its existing contracts:

```bash
python -m pytest -q tests/developer_platform/test_public_examples.py tests/test_extension_examples.py
```

For Studio, use `npm --prefix desktop run typecheck`, `npm --prefix desktop run lint`
and `npm --prefix desktop test`. Run the affected integration/security/recovery
suite too; these small checks do not replace required CI. Native packaging has
its separate [runbook](../acceptance/RELEASE_RUNBOOK.md).

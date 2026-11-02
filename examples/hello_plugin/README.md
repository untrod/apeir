# Hello Plugin

A checksum-bound Plugin manifest declaring `example.echo`, with no filesystem,
network, process, connector or model permission. This is a lifecycle reference,
not an arbitrary third-party executable Plugin demonstration.

From a checkout with development dependencies, run the existing focused test:

```bash
python -m pytest -q tests/test_extension_examples.py::test_plugin_reference_manifest_permissions_lifecycle_and_cleanup
```

It verifies the package checksum, installs into a temporary Runtime root,
enables the declaration, checks that invocation is refused through the old
PluginManager path, then disables and removes it. Passing this test does not
mean `example.echo` ran in a production isolation backend. Do not use the test's
unisolated opt-in as a deployment setting.

Actual execution requires the existing UnifiedExtensionExecutor, current
permissions and a qualified supported isolation profile. Missing prerequisites
stay BLOCKED. For a runnable data-only Studio contribution, use
[System Monitor](../studio_system_monitor/README.md).

The package version is 1.0.1 because this corrected README is part of its hashed
content. Existing 1.0.0 installations are not silently replaced under the same
version. No executable or permission declaration changed.

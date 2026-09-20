# Hello Plugin

A minimal checksum-bound Plugin declaring one capability and no filesystem, network, process, connector, or model permission. Validate or install it only after reviewing `plugin.json` and `plugin_impl.py`.

The focused extension test installs into a temporary Runtime root, enables the capability, invokes it with the test-only isolation opt-in, then disables and uninstalls it. Production execution remains fail-closed unless a supported isolation backend is configured.
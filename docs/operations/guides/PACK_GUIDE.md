# APEIR Pack Guide

## What is a Pack?

A local Pack groups reviewed domain data, Provider declarations and configuration.
Package installation does not grant permissions or prove that its declared tools
can execute. For a runnable new adapter, start with
[Hello Provider](../../../examples/hello_provider/README.md).

<a name="creating-your-first-pack-5-minutes"></a>

## Start from a reviewed example

Inspect the existing [hello manifest](../../../packs/examples/hello_pack/pack.yaml)
and [manifest parser](../../../nous_runtime/pack/manifest.py). Use the current
local command help rather than old scaffold or publishing snippets:

```bash
apeir --no-intelligence pack list
apeir pack --help
```

Only install code whose source you reviewed. The ordinary local Python package
path is not an isolated environment for arbitrary downloaded code.

## Pack Structure

The actual package determines its files and entry points. A `pack.yaml` is parsed
by the existing Pack owner; a directory named `src` or a `register()` function
does not establish permission or successful loading.

## pack.yaml

The current parser requires `name`, `version` and `description`. It accepts
Provider/capability declarations, configuration and dependencies on other Packs.
Do not copy an old `runtime: ">=1.0"` dependency as the current Distribution
version requirement; Pack dependency entries and software release versions are
different contracts. Use the actual parser/example rather than a hypothetical
manifest from an older guide.

## Writing a Provider

Use [the public Provider SDK](../../development/PROVIDER_DEVELOPMENT.md).
New third-party code must not depend on `remote_terminal.nous_core` internals.

## Registration

Host registration and authorization stay with existing Runtime services. A Pack
cannot approve its own Work or create authority through a manifest.

## Testing Your Pack

Test the declared implementation, admission refusal, failure and removal paths.
An installed record or an available catalog entry alone is not execution evidence.
The [read-only Provider example](../../../examples/hello_provider/README.md)
demonstrates an actual governed result without pretending to be arbitrary-code
sandbox qualification.

## Sharing Your Pack

Share reviewed source and the manifest with its exact version and digest.
There is no qualified public Pack publishing service in this preview. Do not
bundle credentials, private Runtime state or implied execution grants.

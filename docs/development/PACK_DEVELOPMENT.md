# Pack Development Guide

## Overview

The [Pack guide](../operations/guides/PACK_GUIDE.md) owns current local usage.
[Pack Model](PACK_MODEL.md) retains the domain-package design reference; it is
not a claim that every described package or future service is implemented.

## Quick Start

Start with [Hello Provider](../../examples/hello_provider/README.md) for an
executable read-only SDK adapter, or [Hello Skill](../../examples/hello_skill/README.md)
for instruction packaging. Both have explicit tested scope. Inspect the
[existing hello manifest](../../packs/examples/hello_pack/pack.yaml) before using
local Pack management.

## Pack Structure

Use the current manifest parser and the package's actual entry points. A copied
scaffold does not establish public SDK compatibility or execution isolation.

## Manifest (pack.yaml)

The authoritative field validation is in the existing
[PackManifest](../../nous_runtime/pack/manifest.py). Versioned dependencies name
other Packs; they are not blanket permission or a software-release certification.

## Writing a Provider

Follow [Provider Development](PROVIDER_DEVELOPMENT.md) and the public
`nous_provider.runtime` contracts. The former `remote_terminal.nous_core`
registration examples are not the recommended external SDK.

## Registration

The host uses the existing Registry and admission owners. Installing a Pack
cannot register its own permission authority or bypass execution checks.

## Testing

Exercise the actual supported host, success/refusal, integrity and removal.
Retain original Work/results when a response is lost. Contract probes and package
metadata are separate from model, native and physical qualification.

## Distribution

Share exact reviewed source/version/digest. Remote Pack publishing is not a
qualified service, and no future release date is promised by this guide.

## Rules

Preserve canonical Runtime owners, compatibility identifiers and manifest checks.
Do not change Kernel, resolve secrets into package files, or treat installation
as permission. [CONTRIBUTING](../../CONTRIBUTING.md) owns integration rules.
